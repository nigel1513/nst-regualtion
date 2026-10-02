"""law 스키마 쓰기 (spec §3A.3). law 스키마에 쓰는 코드는 이 파일에만 둔다.

- 판본: 법령당 is_current 하나. 지난 판본은 판본 정보만 남는다 (D-9).
- 조문: (law_id, path)로 id를 유지한다. 사라진 경로는 지우되, 내부규정이 인용 중이면 gone_in_mst로 남긴다 (판정 R3).
- 변경 기록: 조 단위로 하위까지 묶은 해시를 비교한다 (판정 R15).
"""
import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date

from reg.core.ingest.loader import norm_title
from reg.core.model import ParsedDoc, Prov
from reg.platform.storage.blob import BlobStore
from reg.sources.lawgo import urls
from reg.sources.lawgo.ids import master_id
from reg.sources.lawgo.xml import AdmrulRow, AnnexRow, LawRow

_NORM = re.compile(r"[\s·ㆍ‧∙・]")
_TOP = re.compile(r"^a(\d+)(?:-(\d+))?$")


@dataclass
class VersionHeader:
    family: str
    source_id: str
    name: str
    abbr: str | None
    kind: str | None
    ministry: str | None
    mst: str
    promulgated_on: date | None
    promulgation_no: str | None
    effective_on: date | None
    revision_kind: str | None
    ministry_code: str | None = None

    @property
    def law_id(self) -> str:
        return master_id(self.family, self.source_id)

    @classmethod
    def from_law(cls, r: LawRow) -> "VersionHeader":
        return cls("law", r.law_id, r.name, r.abbr, r.kind, r.ministry, r.mst, r.promulgated_on, r.promulgation_no,
                   r.effective_on, r.revision_kind, r.ministry_code)

    @classmethod
    def from_admrul(cls, r: AdmrulRow) -> "VersionHeader":
        return cls("admrul", r.admrul_id, r.name, None, r.kind, r.ministry, r.seq, r.issued_on, r.issue_no,
                   r.effective_on, r.revision_kind, r.ministry_code)


def _hash(p: Prov) -> str:
    return hashlib.sha256(_NORM.sub("", (p.heading or "") + "|" + (p.text or "")).encode()).hexdigest()[:32]


def _tops(rows: list[tuple[str, str]]) -> dict[str, str]:
    """조(a32, a11-2)마다 그 조와 하위(a32.p1 …)의 해시를 묶은 해시. 장·절·부칙은 빼다."""
    groups: dict[str, list[str]] = {}
    for path, h in rows:
        top = path.split(".")[0]
        if _TOP.match(top):
            groups.setdefault(top, []).append(f"{path}={h}")
    return {k: hashlib.sha256("|".join(sorted(v)).encode()).hexdigest()[:32] for k, v in groups.items()}


def _order(top: str) -> tuple[int, int]:
    m = _TOP.match(top)
    return (int(m[1]), int(m[2] or 0)) if m else (10**9, 0)


def has_version(conn, mst: str) -> bool:
    return conn.execute("SELECT 1 FROM law.law_version WHERE mst = %s AND articles_loaded", (mst,)).fetchone() is not None


def upsert_master(conn, h: VersionHeader) -> None:
    conn.execute(
        "INSERT INTO law.law_master AS m (law_id, family, source_id, name, name_norm, name_abbr, abbr_norm, kind,"
        " ministry, ministry_code, url, last_synced_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now())"
        " ON CONFLICT (law_id) DO UPDATE SET name = EXCLUDED.name, name_norm = EXCLUDED.name_norm,"
        " name_abbr = COALESCE(EXCLUDED.name_abbr, m.name_abbr), abbr_norm = COALESCE(EXCLUDED.abbr_norm, m.abbr_norm),"
        " kind = COALESCE(EXCLUDED.kind, m.kind), ministry = COALESCE(EXCLUDED.ministry, m.ministry),"
        " ministry_code = COALESCE(EXCLUDED.ministry_code, m.ministry_code),"
        " url = EXCLUDED.url, status = '현행', missing_since = NULL, last_synced_at = now()",
        (h.law_id, h.family, h.source_id, h.name, norm_title(h.name), h.abbr or None,
         norm_title(h.abbr) if h.abbr else None, h.kind, h.ministry, h.ministry_code, urls.page_for(h.family, h.name)))


def apply_version(conn, h: VersionHeader, doc: ParsedDoc, source_document_id: int, run_id: int | None = None) -> dict:
    """현행 판본 하나를 적재한다. 호출자가 커밋한다 (법령 하나 = 트랜잭션 하나)."""
    upsert_master(conn, h)
    if has_version(conn, h.mst):
        return {"skipped": 1}
    prev = conn.execute("SELECT mst FROM law.law_version WHERE law_id = %s AND is_current", (h.law_id,)).fetchone()
    prev_mst = prev["mst"] if prev and prev["mst"] != h.mst else None
    conn.execute(
        "INSERT INTO law.law_version (mst, law_id, promulgated_on, promulgation_no, effective_on, revision_kind,"
        " source_document_id, xml_url, html_url) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)"
        " ON CONFLICT (mst) DO UPDATE SET source_document_id = EXCLUDED.source_document_id",
        (h.mst, h.law_id, h.promulgated_on, h.promulgation_no, h.effective_on, h.revision_kind, source_document_id,
         urls.drf_xml(h.family, h.mst), urls.drf_html(h.family, h.mst)))
    # 부분 유일 인덱스(법령당 현행 1개)는 행마다 검사하므로 두 문장으로 바꾼다
    conn.execute("UPDATE law.law_version SET is_current = false WHERE law_id = %s AND is_current", (h.law_id,))
    conn.execute("UPDATE law.law_version SET is_current = true WHERE mst = %s", (h.mst,))
    conn.execute("UPDATE law.law_master SET current_mst = %s WHERE law_id = %s", (h.mst, h.law_id))
    st = _replace_articles(conn, h, doc, prev_mst, run_id)
    conn.execute("UPDATE law.law_version SET articles_loaded = true WHERE mst = %s", (h.mst,))
    return st


def _replace_articles(conn, h: VersionHeader, doc: ParsedDoc, prev_mst: str | None, run_id: int | None) -> dict:
    old = {r["path"]: r for r in conn.execute(
        "SELECT id, path, unit, text_hash, deleted, gone_in_mst FROM law.article WHERE law_id = %s",
        (h.law_id,)).fetchall()}
    live = {p: r for p, r in old.items() if r["gone_in_mst"] is None}
    old_tops = _tops([(p, r["text_hash"]) for p, r in live.items()])
    old_deleted = {p for p, r in live.items() if r["unit"] == "article" and r["deleted"]}
    rows, seen = [], set()
    for i, p in enumerate(doc.provisions):
        if p.path in seen:  # 원문 이상으로 같은 경로가 또 나오면 첫 것만
            continue
        seen.add(p.path)
        rows.append((i, p, _hash(p)))
    for i, p, hsh in rows:
        art = p.unit == "article"
        vals = (h.mst, p.unit, p.parent, urls.jo_code(p.path) if art else None, p.label, p.heading, p.text or "", i,
                p.effective_override or h.effective_on, hsh, p.deleted,
                urls.article_page(h.family, h.name, p.path) if art else None)
        if p.path in old:
            conn.execute("UPDATE law.article SET mst = %s, unit = %s, parent_path = %s, jo_code = %s, label = %s,"
                         " heading = %s, text = %s, ord = %s, effective_on = %s, text_hash = %s, deleted = %s, url = %s,"
                         " gone_in_mst = NULL WHERE id = %s", (*vals, old[p.path]["id"]))
        else:
            conn.execute("INSERT INTO law.article (mst, unit, parent_path, jo_code, label, heading, text, ord,"
                         " effective_on, text_hash, deleted, url, law_id, path)"
                         " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (*vals, h.law_id, p.path))
    kept = 0
    for path, r in old.items():
        if path in seen:
            continue
        cited = conn.execute("SELECT 1 FROM regulation.reference WHERE target_law_article_id = %s LIMIT 1",
                             (r["id"],)).fetchone()
        if cited:
            conn.execute("UPDATE law.article SET gone_in_mst = COALESCE(gone_in_mst, %s) WHERE id = %s", (h.mst, r["id"]))
            kept += 1
        else:
            conn.execute("DELETE FROM law.article WHERE id = %s", (r["id"],))
    new_tops = _tops([(p.path, hsh) for _, p, hsh in rows])
    new_deleted = {p.path for _, p, _ in rows if p.unit == "article" and p.deleted}
    changes: list[tuple[str | None, str, str | None]] = []
    if prev_mst is None:
        changes.append((None, "law_added", None))
    else:
        for top in sorted(set(old_tops) | set(new_tops), key=_order):
            if top not in old_tops:
                kind = "added"
            elif top not in new_tops or (top in new_deleted and top not in old_deleted):
                kind = "deleted"
            elif old_tops[top] != new_tops[top]:
                kind = "modified"
            else:
                continue
            changes.append((top, kind, urls.article_label(top)))
    for path, kind, label in changes:
        conn.execute("INSERT INTO law.change_log (run_id, law_id, from_mst, to_mst, path, change, label)"
                     " VALUES (%s,%s,%s,%s,%s,%s,%s)", (run_id, h.law_id, prev_mst, h.mst, path, kind, label))
    n = Counter(kind for _, kind, _ in changes)
    return {"articles": len(rows), "added": n["added"], "modified": n["modified"], "deleted": n["deleted"],
            "kept_cited": kept}


def mark_abolished(conn, law_id: str, run_id: int | None = None) -> bool:
    n = conn.execute("UPDATE law.law_master SET status = '폐지', missing_since = COALESCE(missing_since, CURRENT_DATE)"
                     " WHERE law_id = %s AND status = '현행'", (law_id,)).rowcount
    if n:
        conn.execute("INSERT INTO law.change_log (run_id, law_id, to_mst, change)"
                     " SELECT %s, law_id, current_mst, 'law_abolished' FROM law.law_master WHERE law_id = %s",
                     (run_id, law_id))
    return bool(n)


def record_annexes(conn, law_id: str, family: str, rows: list[AnnexRow], complete: bool = True) -> int:
    """그 법령의 별표 목록을 맞춘다. complete면 목록에 없는 기존 별표는 is_current=false (메타데이터·저장본은 남김)."""
    new = 0
    for r in rows:
        cur = conn.execute(
            "INSERT INTO law.annex AS a (seq, family, law_id, mst, number, kind, title, promulgated_on, file_path,"
            " pdf_path, view_url) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            " ON CONFLICT (seq) DO UPDATE SET law_id = EXCLUDED.law_id, mst = EXCLUDED.mst, number = EXCLUDED.number,"
            " kind = EXCLUDED.kind, title = EXCLUDED.title, promulgated_on = EXCLUDED.promulgated_on,"
            " file_path = EXCLUDED.file_path, pdf_path = EXCLUDED.pdf_path, view_url = EXCLUDED.view_url,"
            " is_current = true RETURNING (xmax = 0) AS inserted",
            (r.seq, family, law_id, r.owner_key, r.number, r.kind, r.title, r.promulgated_on, r.file_path, r.pdf_path,
             urls.annex_page(family, r.seq, r.owner_key)))
        new += int(cur.fetchone()["inserted"])
    if complete:
        conn.execute("UPDATE law.annex SET is_current = false WHERE law_id = %s AND is_current AND NOT (seq = ANY(%s))",
                     (law_id, [r.seq for r in rows]))
    return new


def store_annex_body(conn, blob: BlobStore, seq: str, html: bytes, pdf: bytes | None) -> None:
    """DRF 별표 HTML은 원본 그대로 (파싱 안 함, D-9). PDF는 판정 R5."""
    hk = f"law/annex/{seq}.html"
    blob.put(hk, html, "text/html; charset=utf-8")
    pk = None
    if pdf is not None:
        pk = f"law/annex/{seq}.pdf"
        blob.put(pk, pdf, "application/pdf")
    conn.execute("UPDATE law.annex SET html_key = %s, pdf_key = COALESCE(%s, pdf_key), fetched_at = now()"
                 " WHERE seq = %s", (hk, pk, seq))


def upsert_catalog(conn, rows: list[AdmrulRow]) -> int:
    """행정규칙 카탈로그(이름·ID·소관부처). 같은 ID의 연혁 행은 현행 행을 덮지 않는다."""
    n = 0
    for r in rows:
        n += conn.execute(
            "INSERT INTO law.admrul_catalog AS c (admrul_id, name, name_norm, kind, ministry, current_seq, issued_on,"
            " issue_no, effective_on, revision_kind, status, ministry_code) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            " ON CONFLICT (admrul_id) DO UPDATE SET name = EXCLUDED.name, name_norm = EXCLUDED.name_norm,"
            " kind = EXCLUDED.kind, ministry = EXCLUDED.ministry,"
            " ministry_code = COALESCE(EXCLUDED.ministry_code, c.ministry_code), current_seq = EXCLUDED.current_seq,"
            " issued_on = EXCLUDED.issued_on, issue_no = EXCLUDED.issue_no, effective_on = EXCLUDED.effective_on,"
            " revision_kind = EXCLUDED.revision_kind, status = EXCLUDED.status, last_seen_at = now()"
            " WHERE EXCLUDED.status = '현행' OR c.status <> '현행'",
            (r.admrul_id, r.name, norm_title(r.name), r.kind, r.ministry, r.seq, r.issued_on, r.issue_no,
             r.effective_on, r.revision_kind, r.status, r.ministry_code)).rowcount
    return n


def catalog_row(conn, admrul_id: str) -> AdmrulRow | None:
    r = conn.execute("SELECT * FROM law.admrul_catalog WHERE admrul_id = %s", (admrul_id,)).fetchone()
    if r is None:
        return None
    return AdmrulRow(r["current_seq"], r["admrul_id"], r["name"], r["kind"], r["ministry"], r["issued_on"],
                     r["issue_no"], r["effective_on"], r["revision_kind"], r["status"], r["ministry_code"])
