"""기관 비교 API·저장 (DB 실물, LLM 없음). 기관 4곳의 여비규정을 만들어 비교값을 직접 넣는다."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from reg.api.app import create_app
from reg.compare import store
from reg.compare.config import load
from reg.compare.extract import Cell
from reg.core.effective import Effective
from reg.core.ingest.loader import add_version, rebuild_work, upsert_work
from reg.core.model import ParsedDoc, Prov
from reg.platform.archive import store as _store
from reg.platform.sniff import FileKind
from reg.platform.storage.blob import LocalBlobStore

INSTS = [("KASI", "한국천문연구원", "7일"), ("ETRI", "한국전자통신연구원", "10일"), ("KIST", "한국과학기술연구원", "10일"),
         ("KRISS", "한국표준과학연구원", "10일"), ("KBSI", "한국기초과학지원연구원", None)]


def wid(code: str) -> str:
    return f"kr/reg/{code}/여비규정"


def text(days: str) -> str:
    return f"출장자는 출장 종료일 다음 날을 기점으로 {days} 이내에 출장을 확인할 수 있는 증빙서를 제출하여야 한다."


@pytest.fixture
def seeded(conn, tmp_path):
    blob = LocalBlobStore(tmp_path)
    for n, (code, name, days) in enumerate(INSTS):
        iid = conn.execute("INSERT INTO regulation.institution (code, name, kind) VALUES (%s,%s,'GRI') RETURNING id",
                           (code, name)).fetchone()["id"]
        if days is None:
            continue
        upsert_work(conn, wid(code), "INTERNAL_REG", "여비규정", iid, {})
        sid = _store(conn, blob, source="alio", url="u", content=b"%PDF-c" + bytes([n]),
                     kind=FileKind("application/pdf", "pdf"), meta={}).id
        provs = [Prov("a1", "article", "제1조", "목적", "이 규정은 여비 지급에 관한 사항을 정함을 목적으로 한다."),
                 Prov("a27", "article", "제27조", "출장증빙의 제출", ""),
                 Prov("a27.p1", "paragraph", "①", None, text(days), parent="a27"),
                 Prov("a27.p2", "paragraph", "②", None, "제1항의 증빙서는 전자문서로 낼 수 있다.", parent="a27")]
        d = date(2024, 1, 1)
        add_version(conn, wid(code), sid, ParsedDoc("여비규정", None, [], provs), Effective(d, "supplement", "CONFIRMED", d))
        rebuild_work(conn, wid(code), date(2026, 10, 2))
    conn.commit()
    return conn


def cells(conn) -> None:
    rows = []
    for code, _, days in INSTS[:4]:
        q = f"{days} 이내에 출장을 확인할 수 있는 증빙서를"
        rows.append(Cell("travel", "evidence_deadline", code, "llm", wid(code), wid(code) + "@2024-01-01", 1, "a27.p1",
                         days, days, q, 0.9))
    rows.append(Cell("travel", "per_diem", "KASI", "absent"))
    store.save_cells(conn, rows)
    store.save_topics(conn, {wid(c): [("travel", 1.0, "title")] for c, _, d in INSTS if d})


@pytest.fixture
def api(seeded, migrated, tmp_path):
    cells(seeded)
    with TestClient(create_app(migrated[0], LocalBlobStore(tmp_path))) as c:
        yield c


def test_work_texts_and_topic_store(seeded):
    works = store.work_texts(seeded)
    assert [w.work_id for w in works] == sorted(wid(c) for c, _, d in INSTS if d)
    assert works[0].first_text.startswith("제1조(목적) 이 규정은 여비")
    assert store.save_topics(seeded, {wid("KASI"): [("travel", 1.0, "title"), ("accounting", 0.9, "title")]}) == 2
    seeded.execute("UPDATE regulation.work_topic SET method = 'manual' WHERE topic = 'accounting'")
    seeded.commit()
    store.save_topics(seeded, {wid("KASI"): [("hr", 1.0, "title")], wid("ETRI"): [("travel", 1.0, "title")]})
    got = seeded.execute("SELECT work_id, topic, method FROM regulation.work_topic ORDER BY 1, 2").fetchall()
    assert [(r["work_id"], r["topic"], r["method"]) for r in got] == [
        (wid("ETRI"), "travel", "title"), (wid("KASI"), "accounting", "manual"), (wid("KASI"), "travel", "title")]
    assert store.topic_works(seeded, "travel") == {"ETRI": [wid("ETRI")], "KASI": [wid("KASI")]}
    assert [w.work_id for w in store.work_texts(seeded, unclassified=True)] == [wid("KIST"), wid("KRISS")]


def test_save_cells_keeps_manual_and_changed_institutions(seeded):
    cells(seeded)
    seeded.execute("UPDATE regulation.compare_cell SET method = 'manual', value = '8일' WHERE institution_code = 'ETRI'")
    seeded.commit()
    cells(seeded)
    assert seeded.execute("SELECT value FROM regulation.compare_cell WHERE institution_code = 'ETRI'").fetchone()["value"] == "8일"
    assert store.changed_institutions(seeded) == ["KBSI"]    # 비교값이 없는 기관만


def test_topics_counts(api):
    t = {x["id"]: x for x in api.get("/api/v1/topics", params={"inst": "KASI"}).json()}
    assert t["travel"]["works"] == 4 and t["travel"]["institutions"] == 4 and t["travel"]["ours"] == 1
    assert t["travel"]["label"] == "여비·출장" and t["travel"]["items"] == 5 and t["hr"]["works"] == 0
    assert "ours" not in api.get("/api/v1/topics").json()[0]
    assert api.get("/api/v1/topics", params={"inst": "NOPE"}).status_code == 400


def test_compare_table(api):
    r = api.get("/api/v1/compare", params={"topic": "travel", "ours": "KASI"}).json()
    assert r["topic"] == "travel" and r["topic_label"] == "여비·출장"
    assert r["institutions"][0]["code"] == "KASI" and r["institutions"][0]["ours"] is True
    assert {i["code"] for i in r["institutions"]} == {"KASI", "ETRI", "KIST", "KRISS"}   # 값이 있는 기관만 기본
    assert r["items"][0] == {"id": "evidence_deadline", "label": "출장 증빙 제출 기한", "unit": "일"}
    ours = r["cells"]["evidence_deadline"]["KASI"]
    assert ours["value"] == "7일" and ours["label"] == "제27조 제1항" and ours["title"] == "여비규정"
    assert ours["href"].startswith("/regulations/kr/reg/KASI/") and ours["href"].endswith("?a=a27#a27.p1")
    assert r["cells"]["evidence_deadline"]["ETRI"]["differs"] is True and ours["differs"] is None
    assert r["cells"]["per_diem"]["KASI"]["status"] == "absent" and r["cells"]["per_diem"]["ETRI"]["status"] == "pending"
    assert r["majority"]["evidence_deadline"] == {"value": "10일", "value_norm": "10일", "count": 3, "total": 4}
    assert r["majority"]["per_diem"] is None and r["built_at"]


def test_compare_selected_institutions_and_errors(api):
    r = api.get("/api/v1/compare", params={"topic": "travel", "inst": "ETRI,KBSI", "ours": "KASI"}).json()
    assert [i["code"] for i in r["institutions"]] == ["KASI", "ETRI", "KBSI"]
    assert r["cells"]["evidence_deadline"]["KBSI"]["status"] == "pending"
    assert api.get("/api/v1/compare", params={"topic": "nope"}).status_code == 404
    assert api.get("/api/v1/compare", params={"topic": "travel", "inst": "ETRI,XXX"}).status_code == 400


def test_divergences(api):
    d = api.get("/api/v1/compare/divergences", params={"inst": "KASI"}).json()
    assert d == [{"topic": "travel", "topic_label": "여비·출장", "item": "evidence_deadline", "item_label": "출장 증빙 제출 기한",
                  "unit": "일", "ours": {"value": "7일", "value_norm": "7일", "work_id": wid("KASI"), "title": "여비규정",
                                        "path": "a27.p1", "label": "제27조 제1항",
                                        "href": d[0]["ours"]["href"]},
                  "majority": {"value": "10일", "value_norm": "10일", "count": 3}, "total": 4}]
    assert api.get("/api/v1/compare/divergences", params={"inst": "ETRI"}).json() == []


def test_provisions_side_by_side_with_highlights(api):
    r = api.get("/api/v1/compare/provisions", params={"topic": "travel", "item": "evidence_deadline",
                                                      "inst": "ETRI", "ours": "KASI"}).json()
    assert r["item"]["label"] == "출장 증빙 제출 기한" and [x["code"] for x in r["institutions"]] == ["KASI", "ETRI"]
    k = r["institutions"][0]
    assert k["article"] == {"path": "a27", "label": "제27조", "heading": "출장증빙의 제출"}
    assert k["effective_from"] == "2024-01-01" and k["version_id"] == wid("KASI") + "@2024-01-01"
    line = next(x for x in k["lines"] if x["path"] == "a27.p1")
    assert line["target"] is True and line["label"] == "①"
    q = next(h for h in line["highlights"] if h["kind"] == "quote")
    v = next(h for h in line["highlights"] if h["kind"] == "value")
    assert line["text"][q["start"]:q["end"]].startswith("7일 이내에") and line["text"][v["start"]:v["end"]] == "7일"
    assert next(x for x in k["lines"] if x["path"] == "a27.p2")["highlights"] == []
    assert api.get("/api/v1/compare/provisions", params={"topic": "travel", "item": "nope"}).status_code == 404
    every = api.get("/api/v1/compare/provisions", params={"topic": "travel", "item": "evidence_deadline"}).json()
    assert len(every["institutions"]) == 4


def test_export_csv(api):
    r = api.get("/api/v1/compare/export.csv", params={"topic": "travel", "inst": "KASI,ETRI"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    body = r.content.decode("utf-8")
    assert body.startswith("﻿주제,항목") and "여비·출장,출장 증빙 제출 기한,일,KASI,한국천문연구원,7일,7일,10일,여비규정" in body
    assert "일비,원,KASI,한국천문연구원,규정 없음" in body


def test_build_orchestration_with_fake_extraction(seeded, monkeypatch):
    from reg.compare import build as B

    store.save_topics(seeded, {wid("KASI"): [("travel", 1.0, "title")]})
    calls = []
    monkeypatch.setattr(B, "candidates", lambda os, emb, rr, item, works: calls.append((item.id, works)) or ["c"])
    monkeypatch.setattr(B, "extract", lambda llm, item, inst, cands: Cell(item.topic, item.id, inst, "llm", wid(inst),
                                                                         None, None, "a27.p1", "7일", "7일", "q", 0.9))
    stats = B.build(seeded, {"os": None, "embedder": None, "llm": None}, load(), topics=["travel"], insts=["KASI", "ETRI"])
    assert stats["cells"] == 10 and stats["values"] == 5 and stats["absent"] == 5     # ETRI는 주제 규정이 없어 LLM 없이
    assert len(calls) == 5 and all(w == [wid("KASI")] for _, w in calls)
    n = seeded.execute("SELECT count(*) n FROM regulation.compare_cell WHERE topic = 'travel'").fetchone()["n"]
    assert n == 10
    dry = B.build(seeded, {"os": None, "embedder": None, "llm": None}, load(), topics=["travel"], insts=["KASI"],
                  dry_run=True)
    assert dry["values"] == 5
