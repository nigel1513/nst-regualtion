# tests/core/test_refs_m66.py
from reg.core.model import Prov
from reg.core.refs import RefContext, collect_abbreviations, extract_refs, match_title


def P(path, text, unit="paragraph", heading=None):
    return Prov(path, unit, "", heading, text)


def _k(refs):
    return [(r.kind, r.name, r.target_path) for r in refs]


def test_unbracketed_regulation_name_is_a_named_ref_not_internal():
    refs = extract_refs(P("a1", "이 요령은 연구관리규정 제2조(정의)에 의거, 필요한 사항을 정한다.", "article", "목적"))
    assert _k(refs) == [("named", "연구관리규정", "a2")]
    assert refs[0].extractor == "rule:name" and refs[0].confidence == 0.9


def test_self_words_and_generic_words_stay_internal():
    assert _k(extract_refs(P("a3", "이 규정 제5조에 따른다."))) == [("internal", None, "a5")]
    assert _k(extract_refs(P("a3", "관련 규정 제5조에 따른다."))) == [("internal", None, "a5")]


def test_defined_abbreviation_and_same_article():
    ctx = RefContext(collect_abbreviations(["「공직자의 이해충돌 방지법」(이하 “법”이라 한다) 및 같은 법 시행령(이하 “영”이라 한다)"]))
    assert ctx.abbreviations == {"법": "공직자의 이해충돌 방지법", "영": "공직자의 이해충돌 방지법 시행령"}
    refs = extract_refs(P("a18", "법 제19조제6항에 따른 이의신청을 하려는 경우 같은 조 제4항 또는 제5항에 따라 영 제3조를 본다."), ctx)
    assert _k(refs)[:4] == [("named", "공직자의 이해충돌 방지법", "a19.p6"),
                            ("named", "공직자의 이해충돌 방지법", "a19"), ("named", "공직자의 이해충돌 방지법", "a19.p4"),
                            ("named", "공직자의 이해충돌 방지법", "a19.p5")]
    assert ("named", "공직자의 이해충돌 방지법 시행령", "a3") in _k(refs)


def test_undefined_bare_law_word_is_not_self():
    assert _k(extract_refs(P("a21.p4", "취소가 가능하며, 시행령 제18조에 따른다."))) == [("named", "시행령", "a18")]


def test_list_carry_and_same_regulation():
    refs = extract_refs(P("a7-2.p1.i1", "이해충돌방지제도시행요령 제2조제2호에 정의된 직무관련자가 동 요령 제2조제3호에 정의된 사람"))
    assert _k(refs) == [("named", "이해충돌방지제도시행요령", "a2.i2"), ("named", "이해충돌방지제도시행요령", "a2.i3")]
    refs = extract_refs(P("supp#122", "보안업무요령 제62조 제1항 별표 제31호, 제63조 제4항 별표 제 34호의 “팀장”을 “실장”으로 한다.",
                          "supplement"))
    assert _k(refs) == [("named", "보안업무요령", "a62.p1"), ("named_annex", "보안업무요령", "annex31"),
                        ("named", "보안업무요령", "a63.p4"), ("named_annex", "보안업무요령", "annex34")]


def test_amendment_supplement_scope():
    text = ("융합연구사업 관리규정 일부를 다음과 같이 개정한다. 제29조제4항제2호 중 \"미래창조과학부\"를"
            " \"과학기술정보통신부\"로 한다. 제30조제6항 중 \"장관\"을 \"부장관\"으로 한다.")
    assert _k(extract_refs(P("supp@2017-09-13/a2.p7", text))) == [
        ("named", "융합연구사업 관리규정", "a29.p4.i2"), ("named", "융합연구사업 관리규정", "a30.p6")]


def test_paragraph_continuation_takes_previous_article():
    refs = extract_refs(P("a33.i18", "공동계약이 가능하다는 뜻(제72조제3항 및 제4항에 의한 공동계약인 경우)", "item"))
    assert [r.target_path for r in refs] == ["a72.p3", "a72.p4"]


def test_contract_template_clauses_inside_annex_are_not_refs():
    text = ("일반조건제1조(총칙) 이행한다. 제2조(규격, 포장 등) ① 충족하여야 한다. 제10조(완료) 제1조의 조건에 부합되지 않으면"
            " 보완을 요구한다. 이 서식은 본문 제5조(관련) 및 (제7조 관련) 서식이다.")
    refs = extract_refs(Prov("form11", "annex", "별지 제11호", None, text))
    assert [r.target_path for r in refs if r.kind == "internal"] == ["a7"]  # '(제7조 관련)'만 본문 참조


def test_match_title_exact_or_institution_prefix_only():
    titles = {"회계규정": ["kr/reg/KASI/회계규정"], "여비규정": ["kr/reg/KASI/여비규정"]}
    pre = frozenset({"한국천문연구원", "KASI", "연구원"})
    assert match_title("한국천문연구원 회계규정", titles, pre) == ["kr/reg/KASI/회계규정"]
    assert match_title("공무원 여비 규정", titles, pre) == []  # 아무 접미부나 맞추지 않는다 (R5)
