import json
from datetime import date
from pathlib import Path

import pytest
import respx

from reg.collect.alio import AlioClient, AlioError, parse_bfiles
from reg.collect.polite import PoliteClient

FX = Path(__file__).parent / "fixtures"
BASE = "https://www.alio.go.kr"


def client():
    return AlioClient(PoliteClient("alio", 0, sleep=lambda s: None))


def test_parse_bfiles_handles_commas_in_names():
    assert parse_bfiles("1|a,b.pdf,22|c.pdf") == [("1", "a,b.pdf"), ("22", "c.pdf")]
    assert parse_bfiles("") == [] and parse_bfiles(None) == []


@respx.mock
def test_list_rules_filters_by_apba_id():
    data = json.loads((FX / "alio_list_kasi_p1.json").read_text())
    data["data"]["result"][2]["apbaId"] = "C9999"  # 부분일치로 섞여 들어온 다른 기관
    respx.get(f"{BASE}/occasional/findRuleList.json").respond(200, json=data)
    rows = list(client().list_rules("한국천문연구원", "C0266"))
    assert [r.seq for r in rows] == ["47852", "10619"]
    assert rows[0].fingerprint  # submissionNo|ruleStDa


@respx.mock
def test_detail_parses_dates_and_files():
    respx.get(f"{BASE}/occasional/findRuleDtl.json").respond(
        200, json=json.loads((FX / "alio_detail.json").read_text()))
    d = client().detail("47852")
    assert d.revised_on == date(2024, 1, 17) and d.posted_on == date(2022, 5, 25)
    assert d.divis == "인사·복무·징계"
    assert [f[0] for f in d.files] == ["151446", "186628"]


@respx.mock
def test_non_json_response_raises():
    respx.get(f"{BASE}/occasional/findRuleDtl.json").respond(200, text="<html>점검중</html>")
    with pytest.raises(AlioError):
        client().detail("1")
