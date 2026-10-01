"""API용 조회. 모든 함수는 dict_row 연결을 받는다."""
from datetime import date

VERSION_COLS = ("v.id, v.work_id, v.title, v.effective_from, v.effective_to, v.version_state, v.effective_status,"
                " v.effective_basis, v.validation_status, v.amendment_kind, v.amendment_no, v.promulgated_on,"
                " v.posted_on, v.class_code, v.source_document_id")


def institutions(conn) -> list[dict]:
    return conn.execute(
        "SELECT i.code, i.name, i.kind, count(w.id)::int AS works FROM regulation.institution i"
        " LEFT JOIN regulation.work w ON w.institution_id = i.id GROUP BY i.id ORDER BY i.id").fetchall()


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def works(conn, institution: str | None, kind: str | None, q: str | None) -> list[dict]:
    rows = conn.execute(
        "SELECT w.id, w.title, w.kind, i.code AS institution,"
        " (SELECT row_to_json(x) FROM (SELECT v.id, v.effective_from, v.version_state, v.effective_status,"
        "   v.validation_status, v.amendment_no FROM regulation.work_version v WHERE v.work_id = w.id"
        "   ORDER BY (v.version_state = 'CURRENT') DESC, v.effective_from DESC NULLS LAST, v.created_at DESC"
        "   LIMIT 1) x) AS version"
        " FROM regulation.work w LEFT JOIN regulation.institution i ON i.id = w.institution_id"
        " WHERE (%(inst)s::text IS NULL OR i.code = %(inst)s)"
        "   AND (%(kind)s::text IS NULL OR (%(kind)s = 'law') = (w.id LIKE 'kr/law/%%'))"
        "   AND (%(q)s::text IS NULL OR w.title ILIKE %(q)s ESCAPE '\\')"
        " ORDER BY i.code NULLS LAST, w.title LIMIT 1000",
        {"inst": institution, "kind": kind, "q": _like(q) if q else None}).fetchall()
    return rows


def work(conn, work_id: str) -> dict | None:
    return conn.execute("SELECT w.id, w.title, w.kind, i.code AS institution FROM regulation.work w"
                        " LEFT JOIN regulation.institution i ON i.id = w.institution_id WHERE w.id = %s",
                        (work_id,)).fetchone()


def versions(conn, work_id: str) -> list[dict]:
    return conn.execute(f"SELECT {VERSION_COLS} FROM regulation.work_version v WHERE v.work_id = %s"
                        " ORDER BY v.effective_from DESC NULLS LAST, v.created_at DESC", (work_id,)).fetchall()


def pick_version(conn, work_id: str, as_of: date | None) -> dict | None:
    if as_of:
        return conn.execute(
            f"SELECT {VERSION_COLS} FROM regulation.work_version v WHERE v.work_id = %s AND v.effective_from <= %s"
            " AND (v.effective_to IS NULL OR v.effective_to > %s) ORDER BY v.effective_from DESC LIMIT 1",
            (work_id, as_of, as_of)).fetchone()
    return conn.execute(
        f"SELECT {VERSION_COLS} FROM regulation.work_version v WHERE v.work_id = %s"
        " ORDER BY (v.version_state = 'CURRENT') DESC, v.effective_from DESC NULLS LAST, v.created_at DESC LIMIT 1",
        (work_id,)).fetchone()


def version_by_id(conn, version_id: str) -> dict | None:
    return conn.execute(f"SELECT {VERSION_COLS} FROM regulation.work_version v WHERE v.id = %s",
                        (version_id,)).fetchone()


def source(conn, source_document_id: int) -> dict:
    sd = conn.execute("SELECT id, source, url, mime, blob_key, view_blob_key, view_status, source_meta"
                      " FROM regulation.source_document WHERE id = %s", (source_document_id,)).fetchone()
    return sd


def provisions(conn, version_id: str) -> list[dict]:
    return conn.execute(
        "SELECT pv.id, pv.provision_id, pv.path, pv.unit, pv.number_label AS label, pv.heading, pv.text,"
        " pv.parent_path AS parent, pv.annotations, pv.deleted, coalesce(vp.anchor, pv.source_anchor) AS anchor,"
        " pv.effective_from_override AS effective_override"
        " FROM regulation.version_provision vp JOIN regulation.provision_version pv ON pv.id = vp.provision_version_id"
        " WHERE vp.work_version_id = %s ORDER BY vp.ord", (version_id,)).fetchall()


def refs_for(conn, pv_ids: list[int]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in conn.execute(
            "SELECT source_pv_id, span_start AS start, span_end AS end, rel_type, target_kind, target_work_id,"
            " target_path, target_name, resolution FROM regulation.reference WHERE source_pv_id = ANY(%s)"
            " ORDER BY source_pv_id, span_start", (pv_ids,)).fetchall():
        out.setdefault(str(r.pop("source_pv_id")), []).append(r)
    return out


def history(conn, version_id: str) -> list[dict]:
    return conn.execute("SELECT kind, date, number FROM regulation.amendment_history WHERE work_version_id = %s"
                        " ORDER BY ord", (version_id,)).fetchall()


def open_tasks(conn, version_id: str) -> list[dict]:
    return conn.execute("SELECT kind, detail FROM regulation.review_task WHERE target = %s AND status = 'OPEN'",
                        (version_id,)).fetchall()


def references(conn, pv_id: int) -> dict:
    pv = conn.execute("SELECT pv.path, p.work_id FROM regulation.provision_version pv JOIN regulation.provision p"
                      " ON p.id = pv.provision_id WHERE pv.id = %s", (pv_id,)).fetchone()
    if not pv:
        return {"outgoing": [], "incoming": []}
    out = conn.execute(
        "SELECT r.span_start AS start, r.span_end AS end, r.evidence_text, r.rel_type, r.target_kind,"
        " r.target_work_id, r.target_path, r.target_name, r.resolution, tw.title AS target_title"
        " FROM regulation.reference r LEFT JOIN regulation.work tw ON tw.id = r.target_work_id"
        " WHERE r.source_pv_id = %s ORDER BY r.span_start", (pv_id,)).fetchall()
    article = pv["path"].split(".")[0]
    inc = conn.execute(
        "SELECT DISTINCT r.evidence_text, r.rel_type, r.target_path, r.resolution, r.work_id AS source_work_id,"
        " sw.title AS source_title, spv.path AS source_path, spv.number_label AS source_label, spv.id AS source_pv_id"
        " FROM regulation.reference r"
        " JOIN regulation.provision_version spv ON spv.id = r.source_pv_id"
        " JOIN regulation.version_provision vp ON vp.provision_version_id = spv.id"
        " JOIN regulation.work_version sv ON sv.id = vp.work_version_id AND sv.version_state = 'CURRENT'"
        " JOIN regulation.work sw ON sw.id = r.work_id"
        " WHERE r.target_work_id = %(w)s AND (r.target_path = %(p)s OR r.target_path = %(a)s"
        "   OR r.target_path LIKE %(p)s || '.%%' OR (r.target_kind = 'WORK' AND %(p)s = %(a)s))"
        " ORDER BY sw.title, spv.path", {"w": pv["work_id"], "p": pv["path"], "a": article}).fetchall()
    return {"outgoing": out, "incoming": inc}


def _pv_map(conn, version_id: str) -> dict[int, dict]:
    return {r["provision_id"]: r for r in conn.execute(
        "SELECT pv.id, pv.provision_id, pv.path, pv.unit, pv.number_label AS label, pv.heading, pv.text,"
        " pv.text_norm_hash, pv.annotations, vp.ord FROM regulation.version_provision vp"
        " JOIN regulation.provision_version pv ON pv.id = vp.provision_version_id WHERE vp.work_version_id = %s",
        (version_id,)).fetchall()}


def diff(conn, from_id: str, to_id: str) -> list[dict]:
    a, b = _pv_map(conn, from_id), _pv_map(conn, to_id)

    def side(x):
        return {k: x[k] for k in ("label", "heading", "text", "annotations")} if x else None

    out = []
    for pid in sorted(a.keys() | b.keys(), key=lambda k: (b[k]["ord"] if k in b else a[k]["ord"] + 0.5)):
        x, y = a.get(pid), b.get(pid)
        if x and y and x["id"] == y["id"]:
            continue
        if x and y:
            same = x["text_norm_hash"] == y["text_norm_hash"] and x["heading"] == y["heading"]
            kind = "RENUMBERED" if x["path"] != y["path"] else ("ANNOTATION_ONLY" if same else "MODIFIED")
        else:
            kind = "ADDED" if y else "DELETED"
        if kind == "ANNOTATION_ONLY" and x["annotations"] == y["annotations"]:
            continue
        ref = y or x
        out.append({"kind": kind, "provision_id": pid, "path": ref["path"], "unit": ref["unit"],
                    "from": side(x), "to": side(y)})
    return out


def search(conn, q: str, institution: str | None) -> list[dict]:
    rows = conn.execute(
        "SELECT w.id AS work_id, w.title, i.code AS institution, v.id AS version_id, pv.path,"
        " pv.number_label AS label, pv.heading, pv.text"
        " FROM regulation.provision_version pv"
        " JOIN regulation.version_provision vp ON vp.provision_version_id = pv.id"
        " JOIN regulation.work_version v ON v.id = vp.work_version_id AND v.version_state = 'CURRENT'"
        " JOIN regulation.work w ON w.id = v.work_id LEFT JOIN regulation.institution i ON i.id = w.institution_id"
        " WHERE pv.text ILIKE %(q)s ESCAPE '\\' AND (%(inst)s::text IS NULL OR i.code = %(inst)s)"
        " ORDER BY w.title, vp.ord LIMIT 50", {"q": _like(q), "inst": institution}).fetchall()
    for r in rows:
        t = r.pop("text")
        pos = t.lower().find(q.lower())
        s = max(pos - 40, 0)
        r["snippet"] = ("…" if s else "") + t[s:pos + len(q) + 40] + ("…" if pos + len(q) + 40 < len(t) else "")
    return rows


def review_tasks(conn, status: str, kind: str | None) -> list[dict]:
    return conn.execute(
        "SELECT t.id, t.kind, t.target, t.work_id, w.title AS work_title, t.detail, t.status, t.created_at"
        " FROM regulation.review_task t LEFT JOIN regulation.work w ON w.id = t.work_id"
        " WHERE t.status = %s AND (%s::text IS NULL OR t.kind = %s) ORDER BY t.created_at DESC, t.id DESC LIMIT 300",
        (status, kind, kind)).fetchall()
