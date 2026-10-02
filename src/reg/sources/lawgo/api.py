"""법령 미러 공개 읽기 API (spec §1A.2 규칙 4). 다른 모듈과 API 계층은 law 스키마를 직접 조회하지 않고 이것을 쓴다."""
import re
from datetime import date

from reg.sources.lawgo import urls
from reg.sources.lawgo.link import resolve_name

MASTER_COLS = "law_id, family, source_id, name, name_abbr, kind, ministry, status, current_mst, url"
VERSION_COLS = "mst, promulgated_on, promulgation_no, effective_on, revision_kind"
ARTICLE_COLS = ("id, law_id, mst, path, unit, parent_path AS parent, label, heading, text, deleted,"
                " gone_in_mst IS NOT NULL AS gone, effective_on, url")
ANNEX_COLS = ("seq, law_id, number, kind, title, promulgated_on, is_current, html_key IS NOT NULL AS has_html,"
              " pdf_key IS NOT NULL AS has_pdf, file_path, pdf_path, view_url")

_SCRIPT = re.compile(rb"<script\b[^>]*>.*?</script\s*>", re.IGNORECASE | re.DOTALL)
_SCRIPT_OPEN = re.compile(rb"<script\b[^>]*>", re.IGNORECASE)
_REFRESH = re.compile(rb"<meta\b[^>]*http-equiv\s*=\s*[\"']?refresh[^>]*>", re.IGNORECASE)
_ON = re.compile(rb"(\s)on[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.IGNORECASE)
_JS = re.compile(rb"(href|src)\s*=\s*([\"']?)\s*javascript:[^\"'>]*\2", re.IGNORECASE)


def _dot(d: date | None) -> str:
    return f"{d.year}. {d.month}. {d.day}." if d else "-"


def _no(no: str | None) -> str | None:
    if not no:
        return None
    return (no.lstrip("0") or no) if no.isdigit() else no


def edition_line(master: dict, version: dict) -> str:
    """law.go.kr 판본 줄: [시행 2026. 9. 11.] [법률 제21421호, 2026. 3. 10., 일부개정]"""
    kind = master.get("kind") or ""
    if master.get("family") == "admrul":
        kind = f"{master.get('ministry') or ''}{kind}"
    no = _no(version.get("promulgation_no"))
    head = f"{kind} 제{no}호" if no else kind
    parts = [p for p in (head.strip(), _dot(version.get("promulgated_on")), version.get("revision_kind")) if p]
    return f"[시행 {_dot(version.get('effective_on'))}] [{', '.join(parts)}]"


def links(master: dict, version: dict | None, article: dict | None = None) -> dict:
    d = {"law_go": master["url"], "law_go_edition": None, "xml": None, "archive": None, "article_go": None}
    if version:
        d["xml"] = urls.drf_xml(master["family"], version["mst"])
        d["archive"] = f"/api/v1/law/version/{version['mst']}/xml"
        if master["family"] == "law" and version.get("promulgation_no") and version.get("promulgated_on"):
            d["law_go_edition"] = urls.law_edition_page(master["name"], _no(version["promulgation_no"]),
                                                        version["promulgated_on"])
    if article:
        d["article_go"] = article.get("url")
    return d


def _master(conn, law_id: str) -> dict | None:
    return conn.execute(f"SELECT {MASTER_COLS} FROM law.law_master WHERE law_id = %s", (law_id,)).fetchone()


def law_summary(conn, law_id: str) -> dict | None:
    m = _master(conn, law_id)
    if m is None:
        return None
    v = conn.execute(f"SELECT {VERSION_COLS} FROM law.law_version WHERE law_id = %s AND is_current",
                     (law_id,)).fetchone()
    past = conn.execute(f"SELECT {VERSION_COLS} FROM law.law_version WHERE law_id = %s AND NOT is_current"
                        " ORDER BY promulgated_on DESC NULLS LAST, mst DESC LIMIT 50", (law_id,)).fetchall()
    for p in past:  # 지난 판본은 판본 정보와 law.go.kr 링크만 (D-9)
        p["edition_line"] = edition_line(m, p)
        p["url"] = (urls.law_edition_page(m["name"], _no(p["promulgation_no"]), p["promulgated_on"])
                    if m["family"] == "law" and p["promulgation_no"] and p["promulgated_on"] else None)
    work = conn.execute("SELECT id FROM regulation.work WHERE law_id = %s ORDER BY id LIMIT 1", (law_id,)).fetchone()
    n = conn.execute("SELECT count(*)::int AS n FROM law.annex WHERE law_id = %s AND is_current", (law_id,)).fetchone()["n"]
    return {"law": m, "version": {**v, "edition_line": edition_line(m, v)} if v else None, "past_versions": past,
            "links": links(m, v), "work_id": work["id"] if work else None, "annex_count": n}


def articles(conn, law_id: str) -> list[dict] | None:
    if _master(conn, law_id) is None:
        return None
    return conn.execute(f"SELECT {ARTICLE_COLS} FROM law.article WHERE law_id = %s AND gone_in_mst IS NULL"
                        " ORDER BY ord", (law_id,)).fetchall()


def article_detail(conn, article_id: int) -> dict | None:
    a = conn.execute(f"SELECT {ARTICLE_COLS} FROM law.article WHERE id = %s", (article_id,)).fetchone()
    if a is None:
        return None
    m = _master(conn, a["law_id"])
    v = conn.execute(f"SELECT {VERSION_COLS} FROM law.law_version WHERE mst = %s", (a["mst"],)).fetchone()
    children = conn.execute(f"SELECT {ARTICLE_COLS} FROM law.article WHERE law_id = %s AND path LIKE %s ORDER BY ord",
                            (a["law_id"], a["path"] + ".%")).fetchall()
    citing = conn.execute(
        "SELECT DISTINCT r.work_id, w.title AS work_title, i.code AS institution, pv.path, pv.number_label AS label,"
        " r.evidence_text, r.rel_type FROM regulation.reference r"
        " JOIN regulation.provision_version pv ON pv.id = r.source_pv_id"
        " JOIN regulation.version_provision vp ON vp.provision_version_id = pv.id"
        " JOIN regulation.work_version v ON v.id = vp.work_version_id AND v.version_state = 'CURRENT'"
        " JOIN regulation.work w ON w.id = r.work_id LEFT JOIN regulation.institution i ON i.id = w.institution_id"
        " WHERE r.target_law_article_id = ANY(%s) ORDER BY i.code NULLS LAST, w.title, pv.path",
        ([a["id"]] + [c["id"] for c in children],)).fetchall()
    return {"article": a, "children": children,
            "law": {k: m[k] for k in ("law_id", "name", "kind", "family", "status")},
            "version": {**v, "edition_line": edition_line(m, v)} if v else None, "links": links(m, v, a),
            "citing": citing}


def _annex(r: dict) -> dict:
    r = dict(r)
    r["file_url"], r["pdf_url"] = urls.file_url(r.pop("file_path")), urls.file_url(r.pop("pdf_path"))
    return r


def annexes(conn, law_id: str) -> list[dict]:
    return [_annex(r) for r in conn.execute(f"SELECT {ANNEX_COLS} FROM law.annex WHERE law_id = %s AND is_current"
                                            " ORDER BY kind, number, seq", (law_id,)).fetchall()]


def annex(conn, seq: str) -> dict | None:
    r = conn.execute(f"SELECT {ANNEX_COLS}, (SELECT name FROM law.law_master m WHERE m.law_id = a.law_id) AS law_name"
                     " FROM law.annex a WHERE seq = %s", (seq,)).fetchone()
    return _annex(r) if r else None


def annex_keys(conn, seq: str) -> dict | None:
    return conn.execute("SELECT html_key, pdf_key FROM law.annex WHERE seq = %s", (seq,)).fetchone()


def version_blob_key(conn, mst: str) -> str | None:
    r = conn.execute("SELECT sd.blob_key FROM law.law_version v JOIN regulation.source_document sd"
                     " ON sd.id = v.source_document_id WHERE v.mst = %s", (mst,)).fetchone()
    return r["blob_key"] if r else None


def citations(conn, version_id: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in conn.execute(
            "SELECT r.source_pv_id, r.span_start AS start, r.span_end AS end, r.target_law_id AS law_id,"
            " r.target_law_article_id AS article_id FROM regulation.reference r"
            " JOIN regulation.version_provision vp ON vp.provision_version_id = r.source_pv_id"
            " WHERE vp.work_version_id = %s AND r.target_law_id IS NOT NULL ORDER BY r.source_pv_id, r.span_start",
            (version_id,)).fetchall():
        out.setdefault(str(r.pop("source_pv_id")), []).append(r)
    return out


def find_law(conn, name: str) -> list[str]:
    return resolve_name(conn, name)


def sanitize_html(data: bytes) -> bytes:
    """저장된 별표 HTML을 내줄 때 스크립트·이벤트 처리기·javascript: 링크·meta refresh를 지운다. 저장본은 그대로 둔다."""
    for rx in (_SCRIPT, _SCRIPT_OPEN, _REFRESH):
        data = rx.sub(b"", data)
    data = _ON.sub(rb"\1", data)
    return _JS.sub(rb'\1="#"', data)
