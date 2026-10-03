"""비교값 추출: 실제 색인(천문연 여비규정) + 가짜 LLM. 인용이 원문에 그대로 있을 때만 값을 받는다."""
import pytest

from reg.compare.config import load
from reg.compare.extract import candidates, extract
from reg.index.indexer import build_release
from reg.index.os import OpenSearch
from tests.test_indexer import FakeEmbedder
from tests.test_search import FakeReranker

WID = "kr/reg/KASI/여비규정"


class LineLLM:
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def regex(self, messages, pattern, **kw):
        self.calls.append(messages)
        import re
        out = self.answers.pop(0)
        assert re.fullmatch(pattern, out), out
        return out


@pytest.fixture
def os_index(loaded, os_url):
    os = OpenSearch(os_url)
    build_release(loaded, os, FakeEmbedder(), "fake")
    return os


@pytest.fixture
def item():
    return load().item("travel", "evidence_deadline")


def test_candidates_are_articles_of_given_works_only(os_index, item):
    cands = candidates(os_index, FakeEmbedder(), FakeReranker(), item, [WID])
    assert cands and cands[0].work_id == WID and cands[0].article_path == "a27"
    assert "7일 이내에" in cands[0].text and any(u.path == "a27.p1" and u.pv_id for u in cands[0].units)
    assert candidates(os_index, FakeEmbedder(), FakeReranker(), item, ["kr/reg/KASI/없는규정"]) == []
    assert candidates(os_index, FakeEmbedder(), FakeReranker(), item, []) == []


def test_extract_keeps_verbatim_quote_and_locates_paragraph(os_index, item):
    cands = candidates(os_index, FakeEmbedder(), FakeReranker(), item, [WID])
    llm = LineLLM("근거: C1\n값: 7일 이내\n인용: 7일 이내에 출장을 확인할 수 있는   증빙서를")
    cell = extract(llm, item, "KASI", cands)
    assert (cell.method, cell.value, cell.value_norm, cell.path, cell.work_id) == ("llm", "7일 이내", "7일", "a27.p1", WID)
    assert cell.pv_id and cell.confidence == 0.9 and cell.quote.startswith("7일 이내에")
    assert "출장" in llm.calls[0][1]["content"] and "C1" in llm.calls[0][1]["content"]


def test_paraphrased_quote_is_retried_then_absent(os_index, item):
    cands = candidates(os_index, FakeEmbedder(), FakeReranker(), item, [WID])
    llm = LineLLM("근거: C1\n값: 7일\n인용: 출장 후 일주일 안에 증빙을 낸다",
                  "근거: C1\n값: 7일\n인용: 일주일 안에 증빙")
    cell = extract(llm, item, "KASI", cands)
    assert cell.method == "absent" and cell.value is None and len(llm.calls) == 2
    assert "글자 그대로" in llm.calls[1][1]["content"]


def test_value_must_appear_in_quote(os_index, item):
    cands = candidates(os_index, FakeEmbedder(), FakeReranker(), item, [WID])
    llm = LineLLM("근거: C1\n값: 10일\n인용: 7일 이내에 출장을 확인할 수 있는 증빙서를",
                  "근거: C1\n값: 7일\n인용: 7일 이내에 출장을 확인할 수 있는 증빙서를")
    cell = extract(llm, item, "KASI", cands)
    assert cell.method == "llm" and cell.value_norm == "7일" and len(llm.calls) == 2


def test_no_evidence_is_absent(os_index, item):
    cands = candidates(os_index, FakeEmbedder(), FakeReranker(), item, [WID])
    assert extract(LineLLM("근거: 없음\n값: 없음\n인용: 없음"), item, "KASI", cands).method == "absent"
    assert extract(LineLLM(), item, "KASI", []).note == "후보 없음"


def test_ellipsis_quote_keeps_one_verbatim_fragment():
    from reg.compare.extract import verbatim

    text = "제6조(사전심의) ① 위원회의 심의대상은 다음과 같다.\n1. 국외출장 계획\n② 제출기한은 7일 전으로 한다."
    assert verbatim("① 위원회의 심의대상은 ... 제출기한은 7일 전으로", "7일", text) == "제출기한은 7일 전으로"
    assert verbatim("위원회의 심의대상은 … 없는 구절이다", "있음", text) is None
    assert verbatim("제출기한은 7일 … 위원회의 심의대상은", "있음", text) is None     # 순서가 바뀌면 받지 않는다
    assert verbatim("한 조각뿐인 인용", "x", text) is None


def test_resolve_quote_cleans_and_snaps_to_original_span():
    from reg.compare.extract import _clean, resolve_quote

    text = "① 출장자는 출장 종료 후 1주(국외출장의 경우 2주) 이내에 결재권자의 승인을 득하여 정산한다."
    assert _clean('"출장 종료 후 1주 이내에 정산한다.(신설 2007. 8.30)"') == "출장 종료 후 1주 이내에 정산한다."
    assert _clean("**15일 이내에 제출하여야 한다.**") == "15일 이내에 제출하여야 한다."
    assert resolve_quote("출장 종료 후 1주(국외출장의 경우 2주)", "1주", text)[1] == "exact"
    q, how = resolve_quote("출장 종료후 1주(국외출장의 경우 2주) 이내 결재권자의 승인을 득하여 정산한다", "1주", text)
    assert how == "aligned" and q in text and q.startswith("출장 종료 후 1주")
    assert resolve_quote("출장 종료 후 3주(국외출장의 경우 2주) 이내에 결재권자의 승인을 득하여", "3주", text) is None
    assert resolve_quote("전혀 다른 문장으로 지어낸 인용입니다 여기에", "x", text) is None


def test_table_quote_falls_back_to_verbatim_fragment_with_the_number():
    from reg.compare.extract import resolve_quote

    table = "국내여비지급표 (단위 : 원) 일비 숙박비 식 비 직급 철도운임 정액 25,000 실비 30,000 (1 등급)"
    q, how = resolve_quote("일비 (1일당) 임원 정액 25,000", "25,000", table, table=True)
    assert how == "table" and q == "정액 25,000" and q in table
    assert resolve_quote("일비 (1일당) 임원 정액 25,000", "25,000", table, table=False) is None
    assert resolve_quote("일비 정액 27,000", "27,000", table, table=True) is None


def test_out_of_bounds_amount_is_retried():
    from reg.compare.extract import Candidate, Unit

    item = load().item("travel", "lodging_cap")
    assert item.min == 30000
    text = "국내여비지급표 (단위 : 원) 일비 숙박비 식비 정액 25,000 실비 (상한액: 서울특별시 100,000, 광역시 80,000)"
    cands = [Candidate(WID, WID + "@2024-01-17", "여비규정", "annex1", text, [Unit(1, "annex1", "annex", text)])]
    llm = LineLLM("근거: C1\n값: 25,000\n인용: 정액 25,000", "근거: C1\n값: 100,000\n인용: 서울특별시 100,000")
    cell = extract(llm, item, "KASI", cands)
    assert (cell.method, cell.value_norm, cell.path) == ("llm", "100000", "annex1")
    assert len(llm.calls) == 2 and "보기 어렵다" in llm.calls[1][1]["content"]


def test_quote_with_leading_article_heading_is_accepted():
    """모델이 조 머리('제6조(사전심의위원회 심의대상)')까지 붙여 인용하면 본문과 안 맞아 버려졌다 (KASI 국외출장 사전 심의)."""
    from reg.compare.extract import _clean, resolve_quote

    text = "국외출장을 가고자 하는 직원은 출장 전에 국외출장 사전심의위원회의 심의를 받아야 한다."
    q = _clean("제6조(사전심의위원회 심의대상) 국외출장을 가고자 하는 직원은 출장 전에 국외출장 사전심의위원회의 심의를 받아야 한다.")
    assert resolve_quote(q, "있음", text) == (text, "exact")
