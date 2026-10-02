# tests/core/test_layout.py
from reg.core.extract.layout import is_page_number_line, is_structural, running_key, two_up_gutter
from reg.core.extract.pdf import drop_running, extract_pdf
from reg.core.model import Block
from tests.core.helpers import PDF


def test_two_up_sheet_is_split_at_the_middle():
    boxes = [(70.0, 350.0)] * 30 + [(490.0, 770.0)] * 30
    assert two_up_gutter(boxes, 841.0, 595.0) == 420.5
    assert two_up_gutter(boxes, 595.0, 841.0) is None  # 세로 용지는 가르지 않는다


def test_wide_landscape_table_is_not_split():
    """Review Focus 1: 가로 용지 한 쪽짜리 넓은 표는 가운데를 가로지르는 줄이 있으므로 가르지 않는다."""
    boxes = [(70.0, 350.0)] * 20 + [(490.0, 770.0)] * 20 + [(60.0, 780.0)] * 5
    assert two_up_gutter(boxes, 841.0, 595.0) is None


def test_running_key_ignores_page_numbers_and_page_number_lines():
    assert running_key("- 3 - 보안업무요령") == running_key("- 14 - 보안업무요령")
    assert is_page_number_line("- 3 - 연구관리요령") and is_page_number_line("보안업무요령 - 28 -")
    assert is_page_number_line("12") and is_page_number_line("3 / 98")
    assert not is_page_number_line("제5조(보안담당관) ①연구원의 보안담당관은")
    assert is_structural("별지 제4호 서식") and is_structural("[별표 제 1 호]") and is_structural("제12조(진도)")


def test_two_up_pdf_reads_left_half_then_right_half():
    blocks = extract_pdf((PDF / "etri_twoup_research_mgmt_p2-3.pdf").read_bytes())
    lines = [b.text for b in blocks]
    i9 = next(i for i, t in enumerate(lines) if t.startswith("제9조(협약체결)"))
    i13 = next(i for i, t in enumerate(lines) if t.startswith("제13조(원내위탁)"))
    assert i9 < i13
    # 지금 추출기는 '…합산한 결과 100퍼센트 침에 따라 실행예산을 적정하게…'처럼 두 단을 한 줄로 합쳤다 (62/72줄)
    assert not any("100퍼센트" in t and "실행예산을 적정하게" in t for t in lines)
    assert all(b.bbox[2] - b.bbox[0] < 421 for b in blocks)  # 어떤 줄도 가운데 홈을 넘지 않는다


def _unit(no: int, head: str) -> list:
    body = [Block(f"{no}. 본문 줄 {i}", no, (80.0, 200.0 + 20 * i, 500.0, 210.0 + 20 * i)) for i in range(5)]
    return [(Block(head, no, (82.0, 100.0, 160.0, 112.0)), True), *((b, False) for b in body),
            (Block(f"- {no} - 내자구매요령", no, (280.0, 800.0, 320.0, 810.0)), True)]


def test_form_headings_are_not_taken_for_running_headers():
    """'별지 제N호 서식'은 쪽마다 맨 위에 와서 숫자를 무시하면 같은 줄이지만 머리글이 아니다."""
    units = [_unit(n, f"별지 제{n}호 서식") for n in range(1, 6)]
    lines = [b.text for b in drop_running(units)]
    assert [t for t in lines if t.startswith("별지")] == [f"별지 제{n}호 서식" for n in range(1, 6)]
    assert not [t for t in lines if "내자구매요령" in t]
