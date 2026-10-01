from datetime import date
from pathlib import Path

from reg.structure.law_xml import parse_law_xml

FX = Path(__file__).parent / "fixtures"


def doc():
    return parse_law_xml((FX / "lawgo_service_283849.xml").read_bytes())


def test_law_basic_info():
    d = doc()
    assert d.title == "국가연구개발혁신법"
    assert d.meta["law_id"] == "013774" and d.meta["effective_on"] == "2026-09-11"
    assert d.meta["promulgated_on"] == "2026-03-10" and d.meta["amendment_kind"] == "일부개정"


def test_law_structure():
    d = doc()
    assert d.get("c1").unit == "chapter" and d.get("c1").heading == "총칙"
    a2 = d.get("a2")
    assert a2.heading == "정의" and a2.parent == "c1"
    assert d.get("a2.i1").label == "1." and d.get("a2.i1").text.startswith('"국가연구개발사업"이란')
    assert d.get("a9.p1").label == "①"
    assert any("2026.3.10" in n for n in a2.annotations)


def test_law_supplements_unique_paths():
    d = doc()
    paths = [s.path for s in d.supplements()]
    assert paths and len(paths) == len(set(paths)) and paths[0] == "supp@2020-06-09"
