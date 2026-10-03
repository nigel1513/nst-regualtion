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
