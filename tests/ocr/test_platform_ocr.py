import json

import httpx
import pytest
import respx

from reg.platform.mineru import MineruClient, table_rows, text_lines
from reg.platform.ocr import MineruOcr, OcrError, OcrLine, OcrUnavailable, dump_lines, load_lines, pdf_page_sizes
from tests.ocr.fx import BROKEN
from tests.ocr.mineru_fake import BASE, KEY, MIDDLE, mock_cycle


def test_text_lines_drops_page_furniture_and_scales_boxes():
    lines = text_lines(MIDDLE, {0: (595.0, 842.0)})
    assert [ln["text"] for ln in lines] == [
        "방사선 재해보상기준",
        "제1조(목적) 이 기준은 원자력법 제109조에 따라",
        "종사자의 보호에 기여함을 목적으로 한다.",
        "제2조(정의) 이 기준에서 종사자라 함은 상근 임직원을 말한다.",
        "구분 | 금액",
        "사망 | 1,000 만원",
    ]  # 머리글·쪽번호는 빠지고, 굵은 글씨 조각은 이어 붙고, 표는 행마다 한 줄
    assert {ln["page"] for ln in lines} == {1}
    assert lines[1]["bbox"] == pytest.approx([59.5, 168.4, 535.5, 252.6])
    assert lines[2]["bbox"] == lines[1]["bbox"]  # 같은 문단은 같은 상자


def test_text_lines_without_page_size_gives_no_box():
    assert all(ln["bbox"] is None for ln in text_lines(MIDDLE, {}))


def test_table_rows_fallback_for_plain_text_body():
    assert table_rows("구분  금액\n사망  1,000") == ["구분 금액", "사망 1,000"]
    assert table_rows("<table><tr><td></td><td></td></tr></table>") == []


def test_pdf_page_sizes_and_line_roundtrip():
    sizes = pdf_page_sizes(BROKEN.read_bytes())
    assert len(sizes) == 4 and sizes[0] == pytest.approx((595.0, 842.0), abs=1)
    lines = [OcrLine("제1조(목적)", 3, (59.5, 168.4, 535.5, 252.6)), OcrLine("표 없음", 4, None)]
    assert load_lines(dump_lines(lines)) == lines


def test_mineru_ocr_forces_ocr_mode_and_maps_lines():
    with respx.mock(assert_all_called=False) as m:
        r = mock_cycle(m, BROKEN.read_bytes())
        res = MineruOcr(MineruClient(BASE, KEY, poll_interval=0)).ocr(BROKEN.read_bytes())
    assert json.loads(r["submit"].calls[0].request.content)["ocr_mode"] == "ocr"
    assert res.engine == "mineru-4.0.0-standard" and res.raw == MIDDLE and res.markdown.startswith("#")
    first = res.lines[1]
    assert (first.text, first.page) == ("제1조(목적) 이 기준은 원자력법 제109조에 따라", 1)
    assert first.bbox == pytest.approx((59.5, 168.4, 535.5, 252.6), abs=1)  # 원본 PDF 쪽 크기로 환산


def test_mineru_ocr_error_mapping():
    eng = MineruOcr(MineruClient(BASE, KEY, poll_interval=0))
    with respx.mock() as m:
        m.post(f"{BASE}/v1/uploads").mock(side_effect=httpx.ConnectError("refused"))
        with pytest.raises(OcrUnavailable):
            eng.ocr(BROKEN.read_bytes())
    with respx.mock(assert_all_called=False) as m:
        mock_cycle(m, BROKEN.read_bytes(), final="failed")
        with pytest.raises(OcrError, match="failed"):
            eng.ocr(BROKEN.read_bytes())
    with respx.mock(assert_all_called=False) as m:
        mock_cycle(m, BROKEN.read_bytes(), middle={**MIDDLE, "pages": [{"page_idx": 0, "blocks": []}]})
        with pytest.raises(OcrError, match="글이 없음"):
            eng.ocr(BROKEN.read_bytes())


def test_mineru_ocr_available_uses_health():
    with respx.mock(assert_all_called=False) as m:
        mock_cycle(m, b"x")
        assert MineruOcr(MineruClient(BASE, KEY)).available() is True


def test_text_lines_splits_nested_child_blocks_one_line_each():
    """MinerU 4.0.10 실측 모양: index(목차) 블록의 content는 자식 text 블록 목록이고, 자식의 content가 다시 span 목록이다.
    'text'가 span 종류이자 블록 종류라 span으로 오인하면 목차 전체가 한 줄로 붙는다."""
    toc = {"type": "index", "index": 0, "bbox": [0.1, 0.3, 0.9, 0.5], "content": [
        {"type": "text", "content": [{"type": "text", "content": "제 1 조 목적 …… 3"}]},
        {"type": "text", "content": [{"type": "text", "content": "제 2 조 정의 …… 3"}]},
    ]}
    lines = text_lines({"pages": [{"page_idx": 0, "blocks": [toc]}]}, {0: (595.0, 842.0)})
    assert [ln["text"] for ln in lines] == ["제 1 조 목적 …… 3", "제 2 조 정의 …… 3"]
