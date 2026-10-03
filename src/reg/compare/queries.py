"""기관 비교 읽기 (API): 주제 목록·비교표·우리 기관이 다른 점·조문 나란히·CSV. LLM 없이 DB만 읽는다.

조문 위치는 (work_id, path)로 그 규정의 현행 판본에서 다시 찾는다. 재파싱으로 provision_version id가 바뀌어도 그대로 쓴다."""
import csv
import io
from collections import Counter
from urllib.parse import quote

from reg.compare.config import Config
from reg.compare.normalize import majority, path_label, quote_span, value_span

DEFAULT_OTHERS = 5     # 비교 기관 기본 수 (우리 기관 + 5, spec §4)
UNITS_SHOWN = ("article", "paragraph", "item", "subitem", "annex", "supplement", "supp_article")

CURRENT = "EXISTS (SELECT 1 FROM regulation.work_version v WHERE v.work_id = w.id AND v.version_state = 'CURRENT')"


def href(work_id: str, path: str) -> str:
    article = path.split(".")[0]
    return "/regulations/" + "/".join(quote(s, safe="") for s in work_id.split("/")) + f"?a={quote(article, safe='')}#{quote(path, safe='')}"


def topics(conn, cfg: Config, inst: str | None = None) -> list[dict]:
    rows = conn.execute(
        "SELECT t.topic, count(DISTINCT w.id)::int AS works, count(DISTINCT w.institution_id)::int AS institutions,"
        " count(DISTINCT w.id) FILTER (WHERE i.code = %s)::int AS ours"
        " FROM regulation.work_topic t JOIN regulation.work w ON w.id = t.work_id"
        " JOIN regulation.institution i ON i.id = w.institution_id"
        f" WHERE w.status <> 'ABOLISHED' AND {CURRENT} GROUP BY t.topic", (inst,)).fetchall()
    by = {r["topic"]: r for r in rows}
    out = []
    for t in cfg.topics:
        r = by.get(t.id) or {"works": 0, "institutions": 0, "ours": 0}
        d = {"id": t.id, "label": t.label, "description": t.description, "works": r["works"],
             "institutions": r["institutions"], "items": len(cfg.items.get(t.id, []))}
        if inst:
            d["ours"] = r["ours"]
        out.append(d)
    return out


def _cells(conn, topic: str) -> list[dict]:
    return conn.execute(
        "SELECT c.*, w.title FROM regulation.compare_cell c LEFT JOIN regulation.work w ON w.id = c.work_id"
        " WHERE c.topic = %s", (topic,)).fetchall()


def institutions(conn) -> list[dict]:
    return conn.execute("SELECT code, name FROM regulation.institution WHERE active ORDER BY id").fetchall()


def _cell_view(r: dict | None) -> dict:
    if r is None:
        return {"status": "pending", "value": None, "value_norm": None, "work_id": None, "title": None, "path": None,
                "label": None, "quote": None, "href": None, "confidence": None}
    if r["method"] == "absent" or (r["work_id"] and r.get("title") is None):   # 규정이 없어진 칸도 '규정 없음'
        return {**_cell_view(None), "status": "absent"}
    return {"status": "value", "value": r["value"], "value_norm": r["value_norm"], "work_id": r["work_id"],
            "title": r["title"], "path": r["path"], "label": path_label(r["path"]), "quote": r["quote"],
            "href": href(r["work_id"], r["path"]), "confidence": r["confidence"]}


def _majorities(cfg: Config, topic: str, rows: list[dict]) -> dict[str, dict | None]:
    out = {}
    for item in cfg.items.get(topic, []):
        vals = [r for r in rows if r["item"] == item.id and r["method"] != "absent" and r["value_norm"]]
        m = majority([r["value_norm"] for r in vals])
        if m is None:
            out[item.id] = None
            continue
        shown = Counter(r["value"] for r in vals if r["value_norm"] == m[0]).most_common(1)[0][0]
        out[item.id] = {"value": shown, "value_norm": m[0], "count": m[1], "total": len(vals)}
    return out


def _pick_institutions(cfg: Config, topic: str, rows: list[dict], all_insts: list[dict], ours: str | None) -> list[str]:
    """기본 비교 기관: 비교값이 있는 기관 중 우리 기관과 다른 값이 많은 곳, 그다음 값이 많은 곳 (spec §4)."""
    vals: dict[str, dict[str, str]] = {}
    for r in rows:
        if r["method"] != "absent" and r["value_norm"]:
            vals.setdefault(r["institution_code"], {})[r["item"]] = r["value_norm"]
    mine = vals.get(ours or "", {})
    order = {i["code"]: n for n, i in enumerate(all_insts)}
    others = [c for c in vals if c != ours]
    others.sort(key=lambda c: (-sum(1 for k, v in vals[c].items() if k in mine and mine[k] != v), -len(vals[c]),
                               order.get(c, 999)))
    return ([ours] if ours else []) + others[:DEFAULT_OTHERS]


def compare(conn, cfg: Config, topic: str, insts: list[str] | None, ours: str | None) -> dict:
    rows = _cells(conn, topic)
    all_insts = institutions(conn)
    names = {i["code"]: i["name"] for i in all_insts}
    if insts:
        codes = list(dict.fromkeys(([ours] if ours else []) + insts))     # 우리 기관이 늘 첫 열
    else:
        codes = _pick_institutions(cfg, topic, rows, all_insts, ours)
    by = {(r["item"], r["institution_code"]): r for r in rows}
    items = cfg.items.get(topic, [])
    cells: dict[str, dict] = {}
    for it in items:
        mine = _cell_view(by.get((it.id, ours))) if ours else None
        row = {}
        for c in codes:
            v = _cell_view(by.get((it.id, c)))
            v["differs"] = (v["value_norm"] != mine["value_norm"]) if (
                mine and c != ours and v["value_norm"] and mine["value_norm"]) else None
            row[c] = v
        cells[it.id] = row
    built = max((r["extracted_at"] for r in rows), default=None)
    return {"topic": topic, "topic_label": cfg.topic(topic).label,
            "items": [{"id": i.id, "label": i.label, "unit": i.unit} for i in items],
            "institutions": [{"code": c, "name": names.get(c, c), "ours": c == ours} for c in codes],
            "cells": cells, "majority": _majorities(cfg, topic, rows),
            "built_at": built.isoformat() if built else None}


def divergences(conn, cfg: Config, inst: str, limit: int = 10) -> list[dict]:
    """우리 기관 값이 다수 기관 값과 다른 항목 (홈 '다른 기관과 다른 점', spec §2). 다수가 뚜렷한 것부터."""
    out = []
    for topic in cfg.items:
        rows = _cells(conn, topic)
        maj = _majorities(cfg, topic, rows)
        mine = {r["item"]: r for r in rows if r["institution_code"] == inst}
        for it in cfg.items[topic]:
            r, m = mine.get(it.id), maj.get(it.id)
            if not r or not m or r["method"] == "absent" or not r["value_norm"] or r.get("title") is None:
                continue
            if r["value_norm"] == m["value_norm"]:
                continue
            v = _cell_view(r)
            out.append({"topic": topic, "topic_label": cfg.topic(topic).label, "item": it.id, "item_label": it.label,
                        "unit": it.unit,
                        "ours": {k: v[k] for k in ("value", "value_norm", "work_id", "title", "path", "label", "href")},
                        "majority": {"value": m["value"], "value_norm": m["value_norm"], "count": m["count"]},
                        "total": m["total"]})
    out.sort(key=lambda d: (-d["majority"]["count"] / max(d["total"], 1), -d["majority"]["count"], d["topic"]))
    return out[:limit]


def _current_version(conn, work_id: str) -> dict | None:
    return conn.execute("SELECT id, effective_from FROM regulation.work_version WHERE work_id = %s"
                        " AND version_state = 'CURRENT'", (work_id,)).fetchone()


def _article_lines(conn, version_id: str, path: str) -> tuple[list[dict], str]:
    article = path.split(".")[0]
    rows = conn.execute(
        "SELECT pv.path, pv.unit, pv.number_label, pv.heading, pv.text FROM regulation.version_provision vp"
        " JOIN regulation.provision_version pv ON pv.id = vp.provision_version_id"
        " WHERE vp.work_version_id = %s AND (pv.path = %s OR starts_with(pv.path, %s)) ORDER BY vp.ord",
        (version_id, article, article + ".")).fetchall()
    rows = [r for r in rows if r["unit"] in UNITS_SHOWN]
    hit = path if any(r["path"] == path for r in rows) else article     # 개정으로 항이 없어졌으면 조 전체
    return rows, hit


def provisions(conn, cfg: Config, topic: str, item_id: str, insts: list[str] | None, ours: str | None = None) -> dict:
    """한 항목의 기관별 근거 조문 원문 (조문 나란히). 줄마다 인용·값 위치(highlights: 글자 시작·끝)를 준다."""
    it = cfg.item(topic, item_id)
    rows = {r["institution_code"]: r for r in _cells(conn, topic) if r["item"] == item_id}
    names = {i["code"]: i["name"] for i in institutions(conn)}
    if insts:
        codes = list(dict.fromkeys(([ours] if ours else []) + insts))
    else:
        codes = sorted((c for c, r in rows.items() if r["method"] != "absent"), key=lambda c: (c != ours, c))
    out = []
    for code in codes:
        r = rows.get(code)
        view = _cell_view(r)
        entry = {"code": code, "name": names.get(code, code), "ours": code == ours, **view, "version_id": None,
                 "effective_from": None, "article": None, "lines": []}
        if view["status"] == "value":
            v = _current_version(conn, r["work_id"])
            if v:
                lines, hit = _article_lines(conn, v["id"], r["path"])
                entry.update(version_id=v["id"], effective_from=v["effective_from"].isoformat() if v["effective_from"] else None)
                if lines:
                    head = lines[0]
                    entry["article"] = {"path": head["path"], "label": head["number_label"], "heading": head["heading"]}
                    entry["lines"] = [_line(x, hit, r["quote"], r["value"], it.norm) for x in lines]
        out.append(entry)
    return {"topic": topic, "topic_label": cfg.topic(topic).label,
            "item": {"id": it.id, "label": it.label, "unit": it.unit}, "institutions": out}


def _line(x: dict, hit: str, quote_text: str, value: str, rule: str) -> dict:
    text = x["text"] or ""
    marks = []
    if (q := quote_span(quote_text, text)) is not None:
        marks.append({"start": q[0], "end": q[1], "kind": "quote"})
        if (v := value_span(value, rule, text, q)) is not None:
            marks.append({"start": v[0], "end": v[1], "kind": "value"})
    return {"path": x["path"], "label": x["number_label"], "text": text, "target": x["path"] == hit or
            x["path"].startswith(hit + "."), "highlights": marks}


def export_csv(conn, cfg: Config, topic: str | None, insts: list[str] | None) -> str:
    """비교값 CSV (엑셀에서 한글이 깨지지 않게 BOM을 붙인다)."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["주제", "항목", "단위", "기관 코드", "기관", "값", "정규화 값", "다수 기관 값", "규정", "조문", "인용", "신뢰도"])
    names = {i["code"]: i["name"] for i in institutions(conn)}
    for t in [topic] if topic else list(cfg.items):
        rows = _cells(conn, t)
        maj = _majorities(cfg, t, rows)
        by = {(r["item"], r["institution_code"]): r for r in rows}
        codes = insts or list(names)
        for it in cfg.items.get(t, []):
            for code in codes:
                v = _cell_view(by.get((it.id, code)))
                m = maj.get(it.id)
                w.writerow([cfg.topic(t).label, it.label, it.unit, code, names.get(code, code),
                            v["value"] if v["status"] == "value" else ("규정 없음" if v["status"] == "absent" else ""),
                            v["value_norm"] or "", m["value"] if m else "", v["title"] or "", v["label"] or "",
                            v["quote"] or "", v["confidence"] if v["confidence"] is not None else ""])
    return "﻿" + buf.getvalue()
