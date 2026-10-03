"""검수 화면용 문장·위치·발췌 (서비스 UI 스펙 §6). DB 없이."""
import pytest

from reg.core import review as R


@pytest.mark.parametrize("path,label", [
    ("a13.p2", "제13조 제2항"),
    ("a10-2", "제10조의2"),
    ("a3.i6-2", "제3조 제6호의2"),
    ("a5.p1.i3.s나", "제5조 제1항 제3호 나목"),
    ("a5.p1.i3.s나~13", "제5조 제1항 제3호 나목"),
    ("supp@2020-05-27", "부칙"),
    ("supp@2020-05-27/a1", "부칙 제1조"),
    ("supp#81", "부칙"),
    ("supp#1/a2.i3.s바", "부칙 제2조 제3호 바목"),
    ("annex2", "별표 2"),
    ("annex1-3", "별표 1의3"),
    ("form4", "별지 제4호 서식"),
    ("form4~2", "별지 제4호 서식"),
    ("c5", "제5장"),
    (None, "전체"),
    ("", "전체"),
    ("weird", "weird"),
])
def test_path_label(path, label):
    assert R.path_label(path) == label


def test_article_of():
    assert R.article_of("a13.p2") == "a13"
    assert R.article_of("supp@2020-05-27/a1") is None
    assert R.article_of("annex2") is None


def test_excerpt_highlights_cited_span():
    text = "가" * 100 + "「상법」 제169조에 따른다." + "나" * 100
    ex = R.excerpt(text, 100, "「상법」 제169조", window=20)
    s, e = ex["highlight"]
    assert ex["text"][s:e] == "「상법」 제169조"
    assert ex["text"].startswith("…") and ex["text"].endswith("…")


def test_excerpt_finds_evidence_when_span_shifted():
    text = "이 규정은 「근로기준법」 제74조를 따른다."
    ex = R.excerpt(text, 0, "「근로기준법」 제74조")
    s, e = ex["highlight"]
    assert ex["text"][s:e] == "「근로기준법」 제74조" and not ex["text"].startswith("…")


def test_excerpt_without_match_has_no_highlight():
    ex = R.excerpt("짧은 글", 3, "없는 인용")
    assert ex == {"text": "짧은 글", "highlight": None}


def test_law_pending():
    assert R.is_law_pending("REFERENCE", {"name": "근로기준법"})
    assert R.is_law_pending("REFERENCE", {"name": "공무원 여비 시행규칙"})
    assert R.is_law_pending("REFERENCE", {"name": "부패방지 및 국민권익위원회의 설치와 운영에 관한 법률"})
    assert R.is_law_pending("REFERENCE", {"name": "같은 법 시행령"})
    assert not R.is_law_pending("REFERENCE", {"name": "법"})          # 약칭 정의 없는 맨 이름: 적재돼도 못 잇는다
    assert not R.is_law_pending("REFERENCE", {"name": "시행령"})
    assert not R.is_law_pending("REFERENCE", {"name": "인사규정"})
    assert not R.is_law_pending("REF_LAW_AMBIGUOUS", {"name": "근로기준법"})


@pytest.mark.parametrize("kind,detail,needle", [
    ("REFERENCE", {"name": "인사규정", "evidence": "인사규정 제5조"}, "인사규정 제5조"),
    ("REFERENCE", {"name": "근로기준법", "evidence": "「근로기준법」 제74조"}, "적재"),
    ("REF_LAW_AMBIGUOUS", {"name": "보안업무규정", "candidates": ["1", "2"], "reason": "multiple"}, "2개"),
    ("REF_LAW_GONE", {"name": "구법", "reason": "law_abolished"}, "폐지"),
    ("REF_LAW_GONE", {"name": "민법", "reason": "article_deleted", "target_path": "a3"}, "제3조"),
    ("REF_LAW_GONE", {"name": "민법", "reason": "article_missing", "target_path": "a900"}, "제900조"),
    ("PARSE", {"check": "gap", "missing": [37]}, "제37조"),
    ("PARSE", {"check": "toc", "diff": ["a28-2"]}, "제28조의2"),
    ("EFFECTIVE_DATE", {"basis": "history"}, "개정 이력"),
    ("EFFECTIVE_DATE", {"basis": "none"}, "찾지 못"),
    ("CONFLICT", {"basis": "supplement"}, "충돌"),
    ("LOW_TEXT", {"articles": 13}, "13"),
    ("LOW_TEXT", {"reason": "제N조 조문 형식이 아님", "ocr": "not_needed"}, "조문 형식이 아님"),
    ("ABOLISHED", {"missing_since": "2026-09-01"}, "2026-09-01"),
])
def test_problem_and_todo_are_korean_sentences(kind, detail, needle):
    p, t = R.problem(kind, detail), R.todo(kind, detail)
    assert needle in p
    assert p.endswith(".") and t.endswith(".")


def test_law_pending_todo_says_wait():
    assert "자동" in R.todo("REFERENCE", {"name": "근로기준법"})


def test_unknown_kind_falls_back():
    assert R.problem("NEW_KIND", {"x": 1}) and R.todo("NEW_KIND", {})


def test_department():
    assert R.department("A1044") == {"code": "A1044", "name": "과학기술정보통신부", "scope": "주무부처"}
    assert R.department("A9999")["name"] is None
    assert R.department(None) is None


def test_problem_does_not_repeat_name_already_in_evidence():
    p = R.problem("REFERENCE", {"name": "영년직 연구원 운영지침", "evidence": "「영년직 연구원 운영지침」제3조"})
    assert p.count("영년직") == 1 and p.endswith("「영년직 연구원 운영지침」제3조.")
    assert "「감사규정」 별표 1" in R.problem("REFERENCE", {"name": "감사규정", "evidence": "별표 1"})


def test_problem_avoids_particles_after_variable_words():
    assert R.problem("PARSE", {"check": "gap", "missing": [63, 64, 65, 66]}).endswith("제63조·제64조·제65조 외 1곳.")
    assert R.problem("EFFECTIVE_DATE", {"basis": "history"}).endswith("(근거: 개정 이력).")
