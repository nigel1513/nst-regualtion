"""work·버전 적재와 조항 계보 재구성 (world_law_collect loader 방식 이식, 시행일 순서 재계산)."""
import hashlib
import json
import re
from datetime import date

from reg.core.effective import Effective
from reg.core.model import ParsedDoc, Prov

_NORM = re.compile(r"[\s·ㆍ‧∙・]")
RENUMBER_UNITS = {"article", "paragraph", "item"}


def norm_title(s: str) -> str:
    return _NORM.sub("", s or "")


def text_hash(p: Prov) -> str:
    return hashlib.sha256(_NORM.sub("", (p.heading or "") + "|" + p.text).encode()).hexdigest()[:32]


def work_key_for_regulation(conn, inst_code: str, inst_id: int, title: str, seq: str) -> str:
    row = conn.execute("SELECT id FROM regulation.work WHERE external_ids->>'alio_seq' = %s", (seq,)).fetchone()
    if row:
        return row["id"]
    key = f"kr/reg/{inst_code}/{norm_title(title)}"
    taken = conn.execute("SELECT 1 FROM regulation.work WHERE id = %s", (key,)).fetchone()
    return f"{key}~{seq}" if taken else key


def upsert_work(conn, work_id: str, kind: str, title: str, institution_id: int | None, external_ids: dict) -> None:
    conn.execute(
        "INSERT INTO regulation.work (id, kind, title, institution_id, external_ids) VALUES (%s,%s,%s,%s,%s)"
        " ON CONFLICT (id) DO UPDATE SET title = EXCLUDED.title, external_ids = regulation.work.external_ids || EXCLUDED.external_ids",
        (work_id, kind, title, institution_id, json.dumps(external_ids, ensure_ascii=False)))


def add_version(conn, work_id: str, source_document_id: int, doc: ParsedDoc, eff: Effective,
                posted_on: date | None = None) -> str:
    row = conn.execute("SELECT id FROM regulation.work_version WHERE work_id = %s AND source_document_id = %s",
                       (work_id, source_document_id)).fetchone()
    if row:
        return row["id"]
    base = f"{work_id}@{eff.effective_from.isoformat()}" if eff.effective_from else f"{work_id}@undated-{source_document_id}"
    vid, n = base, 1
    while conn.execute("SELECT 1 FROM regulation.work_version WHERE id = %s", (vid,)).fetchone():
        n += 1
        vid = f"{base}.{n}"
    seen: dict[str, int] = {}
    for p in doc.provisions:  # 원문 서식이 불규칙해 같은 경로가 또 나오면 ~n을 붙여 구분한다
        seen[p.path] = seen.get(p.path, 0) + 1
        if seen[p.path] > 1:
            p.path = f"{p.path}~{seen[p.path]}"
    for p in doc.provisions:
        if p.unit == "article" and p.path in eff.overrides and p.effective_override is None:
            p.effective_override = eff.overrides[p.path]
    last = doc.history[-1] if doc.history else None
    conn.execute(
        "INSERT INTO regulation.work_version (id, work_id, source_document_id, title, promulgated_on, posted_on,"
        " effective_from, effective_basis, effective_status, amendment_kind, amendment_no, class_code, parsed,"
        " parse_stats) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (vid, work_id, source_document_id, doc.title or work_id, eff.promulgated_on, posted_on, eff.effective_from,
         eff.basis, eff.status, doc.meta.get("amendment_kind") or (last.kind if last else None),
         doc.meta.get("promulgation_no") or (last.number if last else None), doc.class_code,
         json.dumps(doc.to_json(), ensure_ascii=False), json.dumps(doc.meta.get("stats", {}))))
    for i, h in enumerate(doc.history):
        conn.execute("INSERT INTO regulation.amendment_history (work_version_id, ord, kind, date, number)"
                     " VALUES (%s,%s,%s,%s,%s)", (vid, i, h.kind, h.date, h.number))
    return vid


def _insert_pv(conn, prov_id: int, p: Prov) -> int:
    return conn.execute(
        "INSERT INTO regulation.provision_version (provision_id, path, unit, number_label, heading, parent_path, text,"
        " text_norm_hash, annotations, deleted, effective_from_override, source_anchor, meta)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (prov_id, p.path, p.unit, p.label, p.heading, p.parent, p.text, text_hash(p),
         json.dumps(p.annotations, ensure_ascii=False), p.deleted, p.effective_override,
         json.dumps(p.anchor) if p.anchor else None, json.dumps(p.meta, ensure_ascii=False))).fetchone()["id"]


def _new_provision(conn, work_id: str, key: str) -> int:
    return conn.execute("INSERT INTO regulation.provision (work_id, lineage_key) VALUES (%s,%s) RETURNING id",
                        (work_id, key)).fetchone()["id"]


def _change(conn, work_id, frm, to, prov_id, from_pv, to_pv, kind) -> None:
    conn.execute("INSERT INTO regulation.provision_change (work_id, from_version_id, to_version_id, provision_id,"
                 " from_pv_id, to_pv_id, kind) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                 (work_id, frm, to, prov_id, from_pv, to_pv, kind))


def rebuild_work(conn, work_id: str, today: date) -> dict:
    conn.execute("DELETE FROM regulation.provision_change WHERE work_id = %s", (work_id,))
    conn.execute("DELETE FROM regulation.version_provision WHERE work_version_id IN"
                 " (SELECT id FROM regulation.work_version WHERE work_id = %s)", (work_id,))
    conn.execute("DELETE FROM regulation.provision WHERE work_id = %s", (work_id,))
    versions = conn.execute(
        "SELECT id, effective_from, parsed FROM regulation.work_version WHERE work_id = %s"
        " ORDER BY effective_from NULLS LAST, created_at, id", (work_id,)).fetchall()
    dated_ids = [v["id"] for v in versions if v["effective_from"]]
    by_id = {v["id"]: v for v in versions}
    for v in versions:
        k = dated_ids.index(v["id"]) if v["id"] in dated_ids else -1
        nxt = by_id[dated_ids[k + 1]]["effective_from"] if 0 <= k < len(dated_ids) - 1 else None
        if v["effective_from"] is None:
            state = "UNDATED"
        elif v["effective_from"] > today:
            state = "FUTURE"
        elif nxt is None or nxt > today:
            state = "CURRENT"
        else:
            state = "HISTORICAL"
        conn.execute("UPDATE regulation.work_version SET effective_to = %s, version_state = %s WHERE id = %s",
                     (nxt, state, v["id"]))

    prev: dict[str, tuple[int, int, Prov]] | None = None  # path -> (provision_id, pv_id, Prov)
    prev_vid = None
    n_changes = 0
    for v in versions:
        doc = ParsedDoc.from_json(v["parsed"])
        cur: dict[str, tuple[int, int, Prov]] = {}
        base = prev if v["effective_from"] else None
        unmatched_prev = dict(base) if base else {}
        pending = []
        for ord_, p in enumerate(doc.provisions):
            if base is not None and p.path in base:
                pid, pvid, old = unmatched_prev.pop(p.path)
                pending.append((ord_, p, pid, pvid, old))
            else:
                pending.append((ord_, p, None, None, None))
        by_hash = {}
        for path, (pid, pvid, old) in unmatched_prev.items():
            if old.unit in RENUMBER_UNITS:
                by_hash.setdefault(text_hash(old), []).append(path)
        for ord_, p, pid, pvid, old in pending:
            kind = None
            if pid is None and base is not None and p.unit in RENUMBER_UNITS and by_hash.get(text_hash(p)):
                old_path = by_hash[text_hash(p)].pop(0)
                pid, pvid, old = unmatched_prev.pop(old_path)
                kind = "RENUMBERED"
            if pid is None:
                pid = _new_provision(conn, work_id, f"{p.path}@{v['id']}")
                new_pv = _insert_pv(conn, pid, p)
                if base is not None:
                    _change(conn, work_id, prev_vid, v["id"], pid, None, new_pv, "ADDED")
                    n_changes += 1
            else:
                same_text = text_hash(old) == text_hash(p) and old.heading == p.heading and old.deleted == p.deleted
                if kind is None and same_text and old.annotations == p.annotations \
                        and old.effective_override == p.effective_override:  # 원문 위치는 버전별(vp.anchor)이라 비교하지 않는다
                    new_pv = pvid
                else:
                    new_pv = _insert_pv(conn, pid, p)
                    kind = kind or ("ANNOTATION_ONLY" if same_text else "MODIFIED")
                if kind:
                    _change(conn, work_id, prev_vid, v["id"], pid, pvid, new_pv, kind)
                    n_changes += 1
            conn.execute("INSERT INTO regulation.version_provision (work_version_id, provision_version_id, ord, anchor)"
                         " VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                         (v["id"], new_pv, ord_, json.dumps(p.anchor) if p.anchor else None))
            cur[p.path] = (pid, new_pv, p)
        for path, (pid, pvid, old) in unmatched_prev.items():
            _change(conn, work_id, prev_vid, v["id"], pid, pvid, None, "DELETED")
            n_changes += 1
        if v["effective_from"]:
            prev, prev_vid = cur, v["id"]
    n_prov = conn.execute("SELECT count(*) AS n FROM regulation.provision WHERE work_id = %s",
                          (work_id,)).fetchone()["n"]
    return {"versions": len(versions), "provisions": n_prov, "changes": n_changes}
