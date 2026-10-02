import io
import zipfile
from pathlib import Path

import pytest

from reg.core.extract import extract

S = Path(__file__).parent / "fixtures" / "samples"


def test_hwp_paragraphs_are_clean():
    blocks = extract((S / "nst-yeobi-18.hwp").read_bytes(), "application/x-hwp", "a.hwp")
    texts = [b.text for b in blocks]
    assert "여비규정" in texts[:5]
    assert any(t.startswith("제9조의2(국내여비의 정산 및 지급)") for t in texts)
    assert all("捤" not in t and "\x0b" not in t for t in texts)


def test_pdf_lines_drop_running_header_and_page_numbers():
    blocks = extract((S / "kasi-yeobi-339.pdf").read_bytes(), "application/pdf", "a.pdf")
    texts = [b.text for b in blocks]
    assert not any(t in ("- 12 -", "2120 여비규정", "여비규정 2120") for t in texts)
    hit = next(b for b in blocks if b.text.startswith("제 27 조 (출장증빙의 제출)"))
    assert hit.page == 12 and len(hit.bbox) == 4


def test_hwpx_paragraphs():
    sec = ('<hs:sec xmlns:hs="urn:hs" xmlns:hp="urn:hp"><hp:p><hp:run><hp:t>제1조(목적) 이 </hp:t>'
           '<hp:t>규정은</hp:t></hp:run></hp:p><hp:p><hp:run><hp:t>②둘째</hp:t></hp:run></hp:p></hs:sec>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Contents/section0.xml", sec)
    blocks = extract(buf.getvalue(), "application/hwp+zip", "a.hwpx")
    assert [b.text for b in blocks] == ["제1조(목적) 이 규정은", "②둘째"]


def test_unknown_mime_rejected():
    with pytest.raises(ValueError):
        extract(b"x", "text/html", "a.html")


def test_hwp_surrogate_pairs_are_combined():
    import struct

    from reg.core.extract.hwp import _para_text

    raw = "제1조 ".encode("utf-16-le") + "𠀀".encode("utf-16-le") + struct.pack("<H", 13)
    t = _para_text(raw)
    assert "𠀀" in t
    t.encode("utf-8")  # 서로게이트 조각이 남으면 UnicodeEncodeError


def test_review_bare_page_numbers_dropped():
    blocks = extract((S / "nst-yeobi-18.view.pdf").read_bytes(), "application/pdf", "a.pdf")
    assert not any(b.text == str(b.page) for b in blocks)  # 쪽번호 줄 (서식 안의 숫자는 본문이라 남는다)
