# tests/core/test_parse_m66.py
from reg.core.model import Block
from reg.core.parse import PARSER_VERSION, annex_heading, parse_blocks


def _doc(*lines):
    return parse_blocks([Block(t) for t in lines])


def test_parser_version_bumped():
    assert PARSER_VERSION == "2026.10.7"


def test_article_heading_with_inner_parentheses():
    d = _doc("징계요령", "제19조(고발) ① 원장은 고발한다.", "② 묵인한 직원은 징계조치해야 한다.",
             "제20조(금품․향응수수(授受)에 대한 특례) ① 금품·향응수수에 대하여는 문책한다.")
    assert d.get("a20").heading == "금품․향응수수(授受)에 대한 특례"
    assert d.get("a19.p2").text == "묵인한 직원은 징계조치해야 한다."


def test_annex_heading_variants():
    assert annex_heading("[별지 제 1 호]<개정 2019.7.5.>") == ("form", 1, None, "<개정 2019.7.5.>")
    assert annex_heading("<별표 제5호의2호>") == ("annex", 5, 2, "")
    assert annex_heading("별지 제4호 서식") == ("form", 4, None, "")
    assert annex_heading("별지 제 1 호>양식에 따라 변경등록을 하여야 한다.") is None  # 본문 인용


def test_amendment_note_in_annex_heading_becomes_annotation():
    d = _doc("요령", "제1조(목적) 정한다.", "[별지 제11호]<개정 2023. 12. 29.>", "계약 일반조건")
    f = d.get("form11")
    assert f.heading is None and f.annotations == ["<개정 2023. 12. 29.>"] and f.text == "계약 일반조건"


def test_glyphs_and_letter_spacing_are_cleaned_in_provisions():
    d = _doc("기준", "제1조(목적) 이 기준은 연구회(이하\U000f0852연구회\U000f0853라 한다)의 설립\U0000f09e운영을 정한다.",
             "[별표 1]", "소 액 구 매 신 청 서")
    assert d.get("a1").text == "이 기준은 연구회(이하“연구회”라 한다)의 설립·운영을 정한다."
    assert d.get("annex1").text == "소액구매신청서"
