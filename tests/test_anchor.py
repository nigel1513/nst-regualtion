from pathlib import Path

from reg.core.extract import extract
from reg.core.extract.pdf import extract_pdf
from reg.core.parse import parse_blocks
from reg.core.anchor import locate

S = Path(__file__).parent / "fixtures" / "samples"


def test_hwp_provisions_get_anchors_from_view_pdf():
    doc = parse_blocks(extract((S / "nst-yeobi-18.hwp").read_bytes(), "application/x-hwp", "a.hwp"))
    n = locate(doc, extract_pdf((S / "nst-yeobi-18.view.pdf").read_bytes()))
    a = doc.get("a9-2")
    assert a.anchor and a.anchor["page"] == 5 and len(a.anchor["bbox"]) == 4
    assert doc.get("a1").anchor["page"] == 2
    arts = [p for p in doc.provisions if p.unit == "article"]
    assert sum(1 for p in arts if p.anchor) / len(arts) > 0.9 and n > len(arts)
    pages = [p.anchor["page"] for p in arts if p.anchor]
    assert pages == sorted(pages)  # 본문 순서대로
