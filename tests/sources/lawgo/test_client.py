from pathlib import Path

import pytest
import respx

from reg.sources.lawgo.client import DRF, make_client, redact
from reg.sources.lawgo.errors import KeyNotApproved, KeyRejected, LawGoError, NotFound, ResponseChanged

FX = Path(__file__).parent / "fixtures"


def client(log=None):
    return make_client("test", log=log, sleep=lambda s: None)


@respx.mock
def test_search_sends_drf_params():
    route = respx.get(f"{DRF}/lawSearch.do").respond(200, content=(FX / "law_list_ddes_p1.xml").read_bytes())
    data = client().search("law", page=2, display=5, sort="ddes")
    q = dict(route.calls[0].request.url.params)
    assert q == {"OC": "test", "target": "law", "type": "XML", "page": "2", "display": "5", "sort": "ddes"}
    assert data.lstrip().startswith(b"<?xml")


@respx.mock
def test_sort_is_not_sent_for_annex_lists():
    route = respx.get(f"{DRF}/lawSearch.do").respond(200, content=(FX / "licbyl_yeobi.xml").read_bytes())
    client().search("licbyl", sort="ddes", search=2, query="공무원 여비 규정")
    q = dict(route.calls[0].request.url.params)
    assert "sort" not in q and q["search"] == "2" and q["query"] == "공무원 여비 규정"


@pytest.mark.parametrize("fixture,exc,msg", [
    ("unapproved.html", KeyNotApproved, "미신청"),
    ("oc_rejected.xml", KeyRejected, "사용자 정보 검증"),
    ("missing_oc.xml", KeyRejected, "필수입력요소"),
    ("law_not_found.xml", NotFound, "본문이 없습니다"),
])
def test_error_pages_raise_precise_errors(fixture, exc, msg):
    with respx.mock:
        respx.get(f"{DRF}/lawService.do").respond(200, content=(FX / fixture).read_bytes())
        with pytest.raises(exc, match=msg):
            client().service("law", "999999999")


@respx.mock
def test_unapproved_page_on_list_is_not_an_empty_list():
    respx.get(f"{DRF}/lawSearch.do").respond(200, content=(FX / "unapproved.html").read_bytes())
    with pytest.raises(KeyNotApproved, match="law 목록"):
        client().search("law")


@respx.mock
def test_html_where_xml_expected_is_response_changed():
    respx.get(f"{DRF}/lawSearch.do").respond(200, content="<html><body>점검 중</body></html>".encode())
    with pytest.raises(ResponseChanged, match="XML이 아닌"):
        client().search("admrul")


@respx.mock
def test_annex_html_is_returned_as_is():
    respx.get(f"{DRF}/lawService.do").respond(200, content=(FX / "licbyl_18272187.html").read_bytes())
    assert b"lsBylInfoP.do?bylSeq=18272187" in client().annex_html("licbyl", "18272187")


def test_empty_oc_is_rejected_before_any_request():
    with pytest.raises(LawGoError, match="REG_LAWGO_OC"):
        make_client("", sleep=lambda s: None)


@respx.mock
def test_request_log_never_contains_oc():
    respx.get(f"{DRF}/lawSearch.do").respond(200, content=(FX / "law_list_ddes_p1.xml").read_bytes())
    logs = []
    make_client("secret-oc", log=logs.append, sleep=lambda s: None).search("law")
    assert logs and all("secret-oc" not in r.url for r in logs) and "OC=***" in logs[0].url


def test_redact_and_file_path_guard():
    assert redact("https://x/DRF/a.do?OC=abc&target=law") == "https://x/DRF/a.do?OC=***&target=law"
    with pytest.raises(ValueError):
        client().file("/DRF/lawService.do?ID=1")
