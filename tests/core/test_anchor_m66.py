# tests/core/test_anchor_m66.py
from pathlib import Path

from reg.core.anchor import locate
from reg.core.extract import extract
from reg.core.extract.pdf import extract_pdf
from reg.core.model import Block
from reg.core.parse import parse_blocks

S = Path(__file__).resolve().parents[1] / "fixtures" / "samples"


def test_hwp_annexes_found_in_view_pdf_by_number():
    doc = parse_blocks(extract((S / "nst-yeobi-18.hwp").read_bytes(), "application/x-hwp", "a.hwp"))
    locate(doc, extract_pdf((S / "nst-yeobi-18.view.pdf").read_bytes()))
    an = {p.path: p.anchor for p in doc.provisions if p.unit == "annex"}
    assert len(an) == 9 and all(an.values())             # 이전에는 0/9
    assert an["annex1"]["page"] == 15 and an["annex7"]["page"] == 27
    assert an["annex5-2"]["page"] == 23


def test_annex_anchor_skips_body_citations():
    doc = parse_blocks([Block("규칙"), Block("제1조(목적) 정한다.", 1, (0, 0, 1, 1)), Block("[별지 제1호]", 2, (0, 0, 1, 1))])
    view = [Block("제1조(목적) 정한다.", 1, (10, 10, 100, 20)),
            Block("별지 제 1 호>양식에 따라 변경등록을 하여야 한다.", 1, (10, 30, 100, 40)),
            Block("<별지 제 1 호>", 3, (10, 50, 100, 60))]
    doc.get("form1").anchor = None
    locate(doc, view)
    assert doc.get("form1").anchor == {"page": 3, "bbox": [10, 50, 100, 60]}
