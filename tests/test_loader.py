from datetime import date

from reg.platform.archive import store
from reg.platform.sniff import FileKind
from reg.core.ingest.loader import add_version, rebuild_work, upsert_work, work_key_for_regulation
from reg.platform.storage.blob import LocalBlobStore
from reg.core.effective import Effective
from reg.core.model import ParsedDoc, Prov

PDF = FileKind("application/pdf", "pdf")


def src(conn, tmp_path, tag: bytes) -> int:
    return store(conn, LocalBlobStore(tmp_path), source="alio", url="u", content=b"%PDF" + tag, kind=PDF, meta={}).id


def doc(*arts):
    return ParsedDoc("여비규정", "2120", [], [Prov(p, "article", f"제{p[1:]}조", h, t) for p, h, t in arts])


def eff(d):
    return Effective(d, "supplement", "CONFIRMED", d)


def setup(conn, tmp_path):
    inst = conn.execute("INSERT INTO regulation.institution (code, name, kind) VALUES ('KASI','한국천문연구원','GRI')"
                        " RETURNING id").fetchone()["id"]
    wid = work_key_for_regulation(conn, "KASI", inst, "여비 규정", "47852")
    upsert_work(conn, wid, "INTERNAL_REG", "여비규정", inst, {"alio_seq": "47852"})
    return wid


def changes(conn, wid, to):
    return sorted((r["kind"], r["path"]) for r in conn.execute(
        "SELECT c.kind, coalesce(t.path, f.path) AS path FROM regulation.provision_change c"
        " LEFT JOIN regulation.provision_version t ON t.id = c.to_pv_id"
        " LEFT JOIN regulation.provision_version f ON f.id = c.from_pv_id"
        " WHERE c.work_id = %s AND c.to_version_id = %s", (wid, to)).fetchall())


def test_work_key_is_stable_by_seq(conn, tmp_path):
    wid = setup(conn, tmp_path)
    assert wid == "kr/reg/KASI/여비규정"
    assert work_key_for_regulation(conn, "KASI", 1, "여비규정(개정)", "47852") == wid
    assert work_key_for_regulation(conn, "KASI", 1, "여비규정", "99999") == "kr/reg/KASI/여비규정~99999"


def test_versions_changes_and_states_in_effective_order(conn, tmp_path):
    wid = setup(conn, tmp_path)
    v1 = doc(("a1", "목적", "이 규정은 여비를 정한다."), ("a2", "정의", "여비란 운임이다."), ("a3", "기타", "따른다."))
    v2 = doc(("a1", "목적", "이 규정은 여비를 정한다."), ("a2", "정의", "여비란 운임과 일비이다."),
             ("a4", "기타", "따른다."))
    v3 = doc(("a1", "목적", "이 규정은 여비를 정한다."), ("a2", "정의", "여비란 운임과 일비이다."))
    # 도착 순서가 시행일 순서와 다르다 (Review Focus 5)
    id3 = add_version(conn, wid, src(conn, tmp_path, b"3"), v3, eff(date(2030, 1, 1)))
    id1 = add_version(conn, wid, src(conn, tmp_path, b"1"), v1, eff(date(2020, 1, 1)))
    id2 = add_version(conn, wid, src(conn, tmp_path, b"2"), v2, eff(date(2024, 1, 17)))
    st = rebuild_work(conn, wid, today=date(2026, 10, 2))
    assert st["versions"] == 3
    rows = {r["id"]: r for r in conn.execute(
        "SELECT id, version_state, effective_to FROM regulation.work_version WHERE work_id=%s", (wid,)).fetchall()}
    assert rows[id1]["version_state"] == "HISTORICAL" and rows[id1]["effective_to"] == date(2024, 1, 17)
    assert rows[id2]["version_state"] == "CURRENT" and rows[id3]["version_state"] == "FUTURE"
    assert changes(conn, wid, id2) == [("MODIFIED", "a2"), ("RENUMBERED", "a4")]
    assert changes(conn, wid, id3) == [("DELETED", "a4")]
    # 변경 없는 a1은 세 버전이 같은 provision_version 행을 공유
    n = conn.execute("SELECT count(DISTINCT pv.id) AS n FROM regulation.provision_version pv"
                     " JOIN regulation.provision p ON p.id = pv.provision_id WHERE p.work_id=%s AND pv.path='a1'",
                     (wid,)).fetchone()["n"]
    assert n == 1


def test_annotation_only_change(conn, tmp_path):
    wid = setup(conn, tmp_path)
    a = doc(("a1", "목적", "이 규정은 여비를 정한다."))
    b = doc(("a1", "목적", "이 규정은 여비를 정한다."))
    b.provisions[0].annotations = ["<개정 2024.1.17.>"]
    add_version(conn, wid, src(conn, tmp_path, b"a"), a, eff(date(2020, 1, 1)))
    vb = add_version(conn, wid, src(conn, tmp_path, b"b"), b, eff(date(2024, 1, 1)))
    rebuild_work(conn, wid, today=date(2026, 10, 2))
    assert changes(conn, wid, vb) == [("ANNOTATION_ONLY", "a1")]


def test_add_version_is_idempotent(conn, tmp_path):
    wid = setup(conn, tmp_path)
    sid = src(conn, tmp_path, b"x")
    d = doc(("a1", "목적", "x"))
    assert add_version(conn, wid, sid, d, eff(date(2020, 1, 1))) == add_version(conn, wid, sid, d, eff(date(2020, 1, 1)))


def test_duplicate_paths_in_one_document_are_kept_distinct(conn, tmp_path):
    wid = setup(conn, tmp_path)
    d = doc(("a1", "목적", "첫째."), ("a1", "목적", "같은 번호가 또 나온 조문."))
    vid = add_version(conn, wid, src(conn, tmp_path, b"d"), d, eff(date(2020, 1, 1)))
    rebuild_work(conn, wid, today=date(2026, 10, 2))
    rebuild_work(conn, wid, today=date(2026, 10, 2))
    paths = [r["path"] for r in conn.execute(
        "SELECT pv.path FROM regulation.version_provision vp JOIN regulation.provision_version pv"
        " ON pv.id = vp.provision_version_id WHERE vp.work_version_id = %s ORDER BY vp.ord", (vid,)).fetchall()]
    assert paths == ["a1", "a1~2"]


def test_review_anchor_only_difference_is_not_a_change(conn, tmp_path):
    wid = setup(conn, tmp_path)
    a, b = doc(("a1", "목적", "같은 본문입니다.")), doc(("a1", "목적", "같은 본문입니다."))
    a.provisions[0].anchor, b.provisions[0].anchor = {"page": 1, "bbox": None}, {"page": 2, "bbox": None}
    add_version(conn, wid, src(conn, tmp_path, b"p1"), a, eff(date(2020, 1, 1)))
    vb = add_version(conn, wid, src(conn, tmp_path, b"p2"), b, eff(date(2024, 1, 1)))
    rebuild_work(conn, wid, today=date(2026, 10, 2))
    assert changes(conn, wid, vb) == []
    pages = [r["page"] for r in conn.execute(
        "SELECT (coalesce(vp.anchor, pv.source_anchor)->>'page')::int AS page FROM regulation.version_provision vp"
        " JOIN regulation.provision_version pv ON pv.id = vp.provision_version_id"
        " JOIN regulation.work_version v ON v.id = vp.work_version_id ORDER BY v.effective_from").fetchall()]
    assert pages == [1, 2]
