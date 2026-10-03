# tests/core/test_refs_same_doc.py
"""문서 안(같은 work) 미해석 참조 (2026-10-03 실측 25,281건) 중 고칠 수 있는 원인.

- 인용 조항 판본이 들어 있는 다른 판본에는 대상이 있는데, 가장 늦은 판본만 봐서 UNRESOLVED (해석)
- 다른 규범의 조·별표가 자기 조·별표로 잡힘 (추출): 반각 낫표 ｢｣, '제40조(직위의 해제), 제41조(당연퇴직)',
  '제64조부터 제68조까지', '제34조 제1항·제5항 및 제36조', '「인사규정」 별표 1', 'X규정 중 다음과 같이 개정한다'
문구는 실제 미해석 행에서 가져왔다.
"""
from datetime import date

from reg.core.effective import Effective
from reg.core.ingest.loader import add_version, rebuild_work, upsert_work
from reg.core.model import ParsedDoc, Prov
from reg.core.refs import extract_refs, resolve_and_store, resolve_refs
from reg.platform.archive import store
from reg.platform.sniff import FileKind
from reg.platform.storage.blob import LocalBlobStore


def P(path, text, unit="paragraph", heading=None):
    return Prov(path, unit, "", heading, text)


def _k(refs):
    return [(r.kind, r.name, r.target_path) for r in refs]


# ---- 추출: 다른 규범의 조·별표는 자기 조·별표가 아니다 ----

def test_halfwidth_corner_brackets_are_names():
    refs = extract_refs(P("a27.p2.i1", "친족(｢민법｣ 제767조에 따른 친족을 말한다)에 대한 통지", "item"))
    assert _k(refs) == [("external", "민법", "a767")]
    mixed = extract_refs(P("supp#3", "｢부패방지 및 국민권익위원회의 설치와 운영에 관한 법률 시행령」 제89조 제1항에 따라 위와 같이",
                           "supplement"))
    assert _k(mixed) == [("external", "부패방지 및 국민권익위원회의 설치와 운영에 관한 법률 시행령", "a89.p1")]


def test_list_continues_through_article_headings():
    refs = extract_refs(P("a8", "영년직 연구원은 인사규정 제40조(직위의 해제), 제41조(당연퇴직) 및 제42조(직권면직)에 준하는"
                                " 사유가 발생하였을 경우", "article"))
    assert _k(refs) == [("named", "인사규정", "a40"), ("named", "인사규정", "a41"), ("named", "인사규정", "a42")]
    refs = extract_refs(P("supp@2021-09-01", "출연연구기관 등의 설립·운영에 관한 법률 제31조(비밀유지의 의무) 및"
                                             " 제35조(벌칙적용에 있어서의 공무원 의제)", "supplement"))
    assert [r.target_path for r in refs] == ["a31", "a35"] and {r.name for r in refs} == {
        "출연연구기관 등의 설립·운영에 관한 법률"}


def test_list_continues_through_ranges_and_paragraph_lists():
    refs = extract_refs(P("a2.p2.i2.s바", "「생명윤리 및 안전에 관한 법률」 제64조부터 제68조까지의 규정에 해당하는 행위", "subitem"))
    assert _k(refs) == [("external", "생명윤리 및 안전에 관한 법률", "a64"),
                        ("external", "생명윤리 및 안전에 관한 법률", "a68")]
    refs = extract_refs(P("a14.p1.i6", "기업지원연구직 운영요령 제34조 제1항·제5항·제7항·제8항 및 제36조에 따른다.", "item"))
    assert ("named", "기업지원연구직 운영요령", "a36") in _k(refs)
    assert not [r for r in refs if r.kind == "internal"]


def test_bracketed_name_followed_by_annex():
    refs = extract_refs(P("a3.p2", "연구근접지원직의 직급은 「인사규정」 별표 1을 따른다. (개정 2020.4.22)"))
    assert ("named_annex", "인사규정", "annex1") in _k(refs)
    assert not [r for r in refs if r.kind == "annex"]
    # 낫표 안이 서식 이름이면 이 문서의 별지다
    refs = extract_refs(P("a12.p2", "변경사항의 경우 2주전 「기술지원 변경의뢰서」(별지 제14호 서식)을 기술지원 담당자에게 제출한다."))
    assert ("annex", None, "form14") in _k(refs)
    refs = extract_refs(P("a7.p3", "「유전자변형생물체법 통합고시」 별지 제2호서식의 시험·연구용 관리대장"))
    assert _k(refs) == [("named_annex", "유전자변형생물체법 통합고시", "form2")]


def test_amendment_scope_written_with_jung():
    text = ("③(다른규정의 개정) 1. 연구업무규정 중 다음과 같이 개정한다. 제24조제1항 중 “지적재산권관리규정”을"
            " “지식재산권관리규정”으로 한다.")
    refs = extract_refs(P("supp#14", text, "supplement"))
    assert ("named", "연구업무규정", "a24.p1") in _k(refs)
    assert not [r for r in refs if r.kind == "internal"]


def test_own_articles_and_annexes_stay_internal():
    """고친 규칙이 자기 조·별표까지 남의 것으로 만들면 안 된다."""
    refs = extract_refs(P("a10.p1", "제5조(정의) 및 제6조에 따라 별지 제2호서식의 신청서를 제출한다. 이 규정 제7조부터 제9조까지를 준용한다."))
    assert _k(refs) == [("internal", None, "a5"), ("internal", None, "a6"), ("annex", None, "form2"),
                        ("internal", None, "a7"), ("internal", None, "a9")]


# ---- 해석: 인용 조항 판본이 속한 모든 판본에서 찾는다 ----

def _inst(conn) -> int:
    return conn.execute("INSERT INTO regulation.institution (code, name, kind) VALUES ('KFRI','한국식품연구원','GRI')"
                        " ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name RETURNING id").fetchone()["id"]


def _version(conn, tmp_path, wid, provs, eff: date):
    sid = store(conn, LocalBlobStore(tmp_path), source="alio", url="u", content=f"%PDF{wid}{eff}".encode(),
                kind=FileKind("application/pdf", "pdf"), meta={}).id
    add_version(conn, wid, sid, ParsedDoc("예산회계규정", None, [], provs),
                Effective(eff, "supplement", "CONFIRMED", None))


def _two_versions(conn, tmp_path):
    """2017판에는 별지가 있고, 2021판 파일에는 별지가 빠졌다. a21·a48은 두 판본에서 글자가 같다(같은 조항 판본).
    2021판에서 제4조가 빠졌고, 2021판에만 있는 a13-2가 옛 제4조제2항을 '이동' 주석으로 가리킨다."""
    wid = "kr/reg/KFRI/예산회계규정"
    upsert_work(conn, wid, "INTERNAL_REG", "예산회계규정", _inst(conn), {})
    a21 = Prov("a21", "article", "제21조", "예산요구", "계정책임자는 별지 제1호 서식의 예산요구서에 의거하여 제4조에 따라 요구한다.")
    a48 = Prov("a48", "article", "제48조", "수입", "수입의뢰서(별지 제5호)에 의하여 수입 조치하고 별지 제9호를 첨부한다.")
    a4 = Prov("a4", "article", "제4조", "원칙", "원칙")
    _version(conn, tmp_path, wid, [a4, Prov("a4.p2", "paragraph", "②", None, "옛 둘째 항", "a4"), a21, a48,
                                   Prov("form1", "annex", "별지 제1호", "예산요구서", "예산요구서"),
                                   Prov("form5", "annex", "별지 제5호", "수입의뢰서", "수입의뢰서")], date(2017, 12, 29))
    _version(conn, tmp_path, wid, [a21, a48,
                                   Prov("a13-2", "article", "제13조의2", "정의", "용어를 말한다.(제4조제2항에서 이동 2021.4.28.)")],
             date(2021, 11, 11))
    rebuild_work(conn, wid, date(2026, 10, 3))
    return wid


def _rows(conn, wid):
    return {(r["evidence_text"], r["target_path"]): r for r in conn.execute(
        "SELECT * FROM regulation.reference WHERE work_id = %s", (wid,)).fetchall()}


def test_target_in_another_version_of_the_same_provision_resolves(conn, tmp_path):
    wid = _two_versions(conn, tmp_path)
    resolve_and_store(conn, wid)
    r = _rows(conn, wid)
    assert (r[("별지 제1호", "form1")]["target_kind"], r[("별지 제1호", "form1")]["resolution"]) == ("ANNEX", "RESOLVED")
    assert r[("별지 제5호", "form5")]["resolution"] == "RESOLVED"
    assert r[("제4조", "a4")]["resolution"] == "RESOLVED"
    # 어느 판본에도 없는 별지는 그대로 미해석
    assert (r[("별지 제9호", "form9")]["target_work_id"], r[("별지 제9호", "form9")]["resolution"]) == (wid, "UNRESOLVED")
    # 인용 조항이 없는 판본에만 있는 대상(옛 번호 '이동' 주석)도 미해석: 판본 밖으로 넓히지 않는다
    assert r[("제4조제2항", "a4.p2")]["resolution"] == "UNRESOLVED"


def test_resolve_refs_reads_only_and_matches_store(conn, tmp_path):
    wid = _two_versions(conn, tmp_path)
    rows, seeds = resolve_refs(conn, wid)
    assert conn.execute("SELECT count(*) AS n FROM regulation.reference").fetchone()["n"] == 0
    resolve_and_store(conn, wid)
    stored = conn.execute("SELECT evidence_text, target_path, resolution FROM regulation.reference WHERE work_id = %s"
                          " ORDER BY source_pv_id, span_start", (wid,)).fetchall()
    assert [(r.evidence, r.target_path, r.resolution) for r in rows] == \
           [(s["evidence_text"], s["target_path"], s["resolution"]) for s in stored]
    assert seeds == set()
