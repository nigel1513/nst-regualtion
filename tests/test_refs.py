from datetime import date

from reg.collect.archive import store
from reg.collect.sniff import FileKind
from reg.load.loader import add_version, rebuild_work, upsert_work
from reg.refs import extract_refs, looks_like_law, resolve_and_store
from reg.storage.blob import LocalBlobStore
from reg.structure.effective import Effective
from reg.structure.model import ParsedDoc, Prov


def P(path, text, unit="paragraph", label="③", heading=None, parent="a27"):
    return Prov(path, unit, label, heading, text, parent)


def test_exception_and_article_ref_with_trailing_ui():
    refs = extract_refs(P("a27.p3", "제1항에도 불구하고 제13조의 근무지내 출장의 경우는 증빙서 제출을 생략할 수 있다."))
    got = [(r.kind, r.target_path, r.rel_type) for r in refs]
    assert ("internal", "a27.p1", "EXCEPTION") in got
    assert ("internal", "a13", "CITATION") in got


def test_branch_article_and_item():
    refs = extract_refs(P("a6-2.p1", "「여신전문금융업법」제2조 제3호에 따른 신용카드"))
    r = refs[0]
    assert (r.kind, r.name, r.target_path, r.rel_type) == ("external", "여신전문금융업법", "a2.i3", "BASIS")
    refs2 = extract_refs(P("a3.p1", "제7조의2제1항을 준용한다."))
    assert [(x.kind, x.target_path, x.rel_type) for x in refs2] == [("internal", "a7-2.p1", "MUTATIS")]


def test_mutatis_external_names_and_previous_paragraph():
    refs = extract_refs(P("a29", "이 규정에서 정하지 아니한 사항은 「공무원 여비규정」 및 「국가공무원 복무·징계 관련 예규」를"
                                 " 준용할 수 있다.", unit="article", label="제29조", heading="기타", parent=None))
    assert [(r.name, r.rel_type) for r in refs] == [("공무원 여비규정", "MUTATIS"),
                                                     ("국가공무원 복무·징계 관련 예규", "MUTATIS")]
    prev = extract_refs(P("a10.p2", "전항의 숙박비는 실비로 지급한다.", parent="a10"))
    assert [(r.kind, r.target_path) for r in prev] == [("internal", "a10.p1")]


def test_annex_and_delegation():
    refs = extract_refs(P("a9", "국내출장에 있어서 여비는 별표 1에 정하는 바에 의하여 지급하고, 세부사항은 원장이 따로 정한다.",
                          unit="article", label="제9조", parent=None))
    assert ("annex", "annex1") in [(r.kind, r.target_path) for r in refs]
    assert any(r.kind == "delegation" and r.rel_type == "DELEGATION" for r in refs)


def test_looks_like_law():
    assert looks_like_law("국가공무원 복무·징계 관련 예규") and looks_like_law("공무원 여비 규정")
    assert not looks_like_law("방문기관확인서")


def _load(conn, tmp_path, wid, kind, title, provs, inst=None, tag=b""):
    upsert_work(conn, wid, kind, title, inst, {})
    sid = store(conn, LocalBlobStore(tmp_path), source="alio", url="u", content=b"%PDF" + wid.encode() + tag,
                kind=FileKind("application/pdf", "pdf"), meta={}).id
    add_version(conn, wid, sid, ParsedDoc(title, None, [], provs), Effective(date(2024, 1, 1), "api", "CONFIRMED", None))
    rebuild_work(conn, wid, date(2026, 10, 2))


def test_resolve_against_laws_and_seed_unknown(conn, tmp_path):
    inst = conn.execute("INSERT INTO regulation.institution (code, name, kind) VALUES ('KASI','천문연','GRI')"
                        " RETURNING id").fetchone()["id"]
    _load(conn, tmp_path, "kr/law/000001", "대통령령", "공무원 여비 규정", [Prov("a1", "article", "제1조", "목적", "x")])
    _load(conn, tmp_path, "kr/reg/KASI/여비규정", "INTERNAL_REG", "여비규정", [
        Prov("a13", "article", "제13조", "근무지내 출장", "근무지내 출장은"),
        Prov("a29", "article", "제29조", "기타", "이 규정에서 정하지 아니한 사항은 「공무원 여비규정」 및 "
             "「국가공무원 복무·징계 관련 예규」를 준용할 수 있다."),
        Prov("a30", "article", "제30조", "적용", "제13조에 따른다.")], inst)
    st = resolve_and_store(conn, "kr/reg/KASI/여비규정")
    rows = conn.execute("SELECT target_name, target_work_id, target_path, resolution, rel_type FROM regulation.reference"
                        " WHERE work_id='kr/reg/KASI/여비규정' ORDER BY id").fetchall()
    by = {(r["target_name"] or r["target_path"]): r for r in rows}
    assert by["공무원 여비규정"]["target_work_id"] == "kr/law/000001" and by["공무원 여비규정"]["resolution"] == "RESOLVED"
    assert by["국가공무원 복무·징계 관련 예규"]["resolution"] == "UNRESOLVED"
    assert by["a13"]["resolution"] == "RESOLVED" and by["a13"]["target_work_id"] == "kr/reg/KASI/여비규정"
    seed = conn.execute("SELECT origin FROM regulation.law_seed WHERE name='국가공무원 복무·징계 관련 예규'").fetchone()
    assert seed["origin"] == "reference" and st["seeds"] == 1
    assert resolve_and_store(conn, "kr/reg/KASI/여비규정")["refs"] == st["refs"]  # 다시 해도 중복 없음
