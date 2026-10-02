"""기록된 실제 응답으로 하는 목록 계약 테스트 (네트워크 없음)."""
from pathlib import Path

import pytest

from reg.sources.lawgo.errors import ResponseChanged
from reg.sources.lawgo.xml import parse_law_xml, parse_list

FX = Path(__file__).parent / "fixtures"


def test_law_list_contract():
    lp = parse_list("law", (FX / "law_list_ddes_p1.xml").read_bytes())
    assert lp.target == "law" and lp.total > 5000 and len(lp.rows) == 5 and lp.page == 1
    assert all(r.mst.isdigit() and r.law_id.isdigit() and r.status == "현행" and r.master_id == r.law_id
               for r in lp.rows)
    dates = [r.promulgated_on for r in lp.rows]
    assert None not in dates and dates == sorted(dates, reverse=True)  # sort=ddes가 동작한다


def test_admrul_list_contract():
    lp = parse_list("admrul", (FX / "admrul_list_ddes_p1.xml").read_bytes())
    assert lp.total > 20000 and len(lp.rows) == 5
    assert {r.status for r in lp.rows} <= {"현행", "연혁"}
    assert all(r.master_id == f"admrul:{r.admrul_id}" and r.seq.isdigit() for r in lp.rows)
    dates = [r.issued_on for r in lp.rows]
    assert dates == sorted(dates, reverse=True)


def test_licbyl_by_law_name_contract():
    lp = parse_list("licbyl", (FX / "licbyl_yeobi.xml").read_bytes())
    assert lp.rows and all(r.family == "law" and r.owner_source_id == "009402" and r.master_id == "009402"
                           for r in lp.rows)
    assert all(r.number and len(r.number) == 6 and r.owner_key.isdigit() for r in lp.rows)
    assert any((r.pdf_path or "").startswith("/LSW/flDownload.do?flSeq=") for r in lp.rows)


def test_admbyl_by_admrul_name_contract():
    lp = parse_list("admbyl", (FX / "admbyl_rnd.xml").read_bytes())
    assert lp.rows and all(r.family == "admrul" and r.master_id == "admrul:75386" for r in lp.rows)
    assert all(r.pdf_path is None and (r.file_path or "").startswith("/LSW/flDownload.do") for r in lp.rows)


def test_list_structure_change_is_reported_precisely():
    bad = '<?xml version="1.0" encoding="UTF-8"?><LawSearch><totalCnt>1</totalCnt><law><법령ID>1</법령ID></law></LawSearch>'
    with pytest.raises(ResponseChanged, match="<법령일련번호>"):
        parse_list("law", bad.encode())
    with pytest.raises(ResponseChanged, match="최상위"):
        parse_list("law", b'<?xml version="1.0"?><Other/>')
    with pytest.raises(ResponseChanged, match="totalCnt"):
        parse_list("law", b'<?xml version="1.0"?><LawSearch/>')
    with pytest.raises(ResponseChanged, match="XML 해석"):
        parse_list("law", b"<html><body>")


def test_law_body_contract_and_guard():
    d = parse_law_xml((FX / "law_287535.xml").read_bytes())
    assert d.title == "공무원 여비 규정" and d.meta["law_id"] == "009402" and d.get("a10") is not None
    with pytest.raises(ResponseChanged, match="기본정보"):
        parse_law_xml('<?xml version="1.0" encoding="UTF-8"?><법령/>'.encode())


def test_list_rows_carry_ministry_code():
    law = parse_list("law", (FX / "law_list_ddes_p1.xml").read_bytes()).rows
    assert all(r.ministry and r.ministry_code and r.ministry_code.isdigit() for r in law)
    adm = parse_list("admrul", (FX / "admrul_list_ddes_p1.xml").read_bytes()).rows
    assert all(r.ministry and r.ministry_code is None for r in adm)  # admrul 목록에는 코드가 없다 (본문에만 있다)


def test_ministry_of_law_and_admrul_bodies():
    from reg.sources.lawgo.xml import ministry_of

    assert ministry_of((FX / "law_287535.xml").read_bytes()) == ("인사혁신처", "1760000")
    assert ministry_of((FX / "admrul_2100000285346.xml").read_bytes()) == ("법무부", "1270000")
