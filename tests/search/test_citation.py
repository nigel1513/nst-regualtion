"""M7 §2.2-1 조문 번호 직접 조회: 인용 파서 표."""
import pytest

from reg.search.citation import parse_citation

ALIASES = {"KASI": ["한국천문연구원", "천문연구원", "천문연", "KASI"], "KIST": ["한국과학기술연구원", "키스트", "KIST"],
           "NST": ["국가과학기술연구회", "과기연구회", "연구회", "NST"]}

CASES = [
    ("천문연 여비규정 27조 1항", {"institution": "KASI", "title": "여비규정", "article": 27, "paragraph": 1}),
    ("여비규정 제27조의2 제1항 제3호", {"title": "여비규정", "article": 27, "branch": 2, "paragraph": 1, "item": 3}),
    ("「국가연구개발혁신법 시행령」 제5조", {"title": "국가연구개발혁신법 시행령", "article": 5}),
    ("한국천문연구원의 여비규정 제27조 ①", {"institution": "KASI", "title": "여비규정", "article": 27, "paragraph": 1}),
    ("복무규정 제26조 제2항 제1호 가목", {"title": "복무규정", "article": 26, "paragraph": 2, "item": 1, "subitem": "가"}),
    ("여비규정 별표 1", {"title": "여비규정", "annex": 1}),
    ("여비규정 별지 제3호 서식", {"title": "여비규정", "annex": 3, "form": True}),
    ("KIST 여비규정 14조", {"institution": "KIST", "title": "여비규정", "article": 14}),
    ("27조 3호의2", {"article": 27, "item": 3, "item_branch": 2}),
    ("연구회 복무규정 제26조제1항", {"institution": "NST", "title": "복무규정", "article": 26, "paragraph": 1}),
    ("여비규정 제27조 제1항 내용 알려줘", {"title": "여비규정", "article": 27, "paragraph": 1}),
]


@pytest.mark.parametrize("q,want", CASES)
def test_parse_citation(q, want):
    c = parse_citation(q, ALIASES)
    assert c is not None
    got = {k: v for k, v in c.as_dict().items() if v not in (None, False)}
    assert got == want


@pytest.mark.parametrize("q", ["출장 다녀온 지 10일 지났어요", "여비규정", "2024년 1월 17일 시행", "",
                               "출장 다녀온 지 27일 지났는데 3항목을 못 냈어요"])
def test_not_a_citation(q):
    assert parse_citation(q, ALIASES) is None


def test_unit_is_the_deepest_level():
    assert parse_citation("여비규정 제27조 제1항 제3호", ALIASES).unit() == "item"
    assert parse_citation("여비규정 제27조", ALIASES).unit() == "article"
    assert parse_citation("여비규정 별지 1", ALIASES).unit() == "form"
