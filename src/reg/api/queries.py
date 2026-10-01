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
