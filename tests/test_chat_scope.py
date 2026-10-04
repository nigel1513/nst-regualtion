"""규정 도우미 범위 (assistant-scope): 규정·주제 범위는 검색 질의 안의 필터이고, 규정을 고르면 기관도 정해진다."""
import pytest

from reg.qa.chat import chat, collect
from tests.test_chat import ALL, HITS, FakeConn, OverviewLLM, fake_expand, fake_search, only  # noqa: F401

KASI_TRAVEL = HITS[0]["work_id"]          # kr/reg/KASI/여비규정
KBSI_TRAVEL = HITS[1]["work_id"]


def _run(conn, llm, q, scope):
    return collect(chat(conn, {"llm": llm}, [{"role": "user", "content": q}], scope, log=False))


def _status(ev):
    return ev[0]["data"]


def test_work_scope_filters_inside_search_and_implies_institution(fake_search, fake_expand):
    ev = _run(FakeConn(), OverviewLLM(), "출장 증빙 제출은 어떻게 하나요?", {"mode": "all", "institutions": [], "work_ids": [KASI_TRAVEL]})
    st = _status(ev)
    assert st["intent"] == "question" and [i["code"] for i in st["institutions"]] == ["KASI"]
    assert st["work_ids"] == [KASI_TRAVEL]
    assert fake_search and all(set(x["work_ids"]) == {KASI_TRAVEL} for x in fake_search)
    cards = next(e["data"]["cards"] for e in ev if e["event"] == "results")
    assert cards and {c["work_id"] for c in cards} == {KASI_TRAVEL}


def test_work_scope_overrides_selected_institutions(fake_search, fake_expand):
    ev = _run(FakeConn(), OverviewLLM(), "출장 증빙 절차", {"mode": "institutions", "institutions": ["KIST"],
                                                     "work_ids": [KBSI_TRAVEL]})
    assert [i["code"] for i in _status(ev)["institutions"]] == ["KBSI"]
    assert fake_search[0]["institution"] == "KBSI" and set(fake_search[0]["work_ids"]) == {KBSI_TRAVEL}


def test_work_scope_over_two_institutions_compares_within_those_works(fake_search):
    from tests.test_chat import ExtractLLM

    ev = _run(FakeConn(), ExtractLLM(), "출장 증빙 기한", {"mode": "all", "institutions": [],
                                                    "work_ids": [KASI_TRAVEL, KBSI_TRAVEL]})
    assert _status(ev)["intent"] == "comparison"
    assert all(set(x["work_ids"]) == {KASI_TRAVEL, KBSI_TRAVEL} for x in fake_search)


def test_compare_words_inside_one_regulation_scope_stay_a_question(fake_search, fake_expand):
    ev = _run(FakeConn(), OverviewLLM(), "출장 증빙 기한은? 다른 기관도", {"mode": "all", "institutions": [],
                                                                 "work_ids": [KASI_TRAVEL]})
    assert _status(ev)["intent"] == "question"


def test_topic_scope_is_a_search_filter(fake_search, fake_expand):
    conn = FakeConn(topics={"travel": [KASI_TRAVEL, KBSI_TRAVEL]})
    ev = _run(conn, OverviewLLM(), "출장 증빙 제출 절차", {"mode": "all", "institutions": [], "work_ids": [], "topic": "travel"})
    assert fake_search and all(set(x["work_ids"]) == {KASI_TRAVEL, KBSI_TRAVEL} for x in fake_search)
    cards = next(e["data"]["cards"] for e in ev if e["event"] == "results")
    assert {c["institution"]["code"] for c in cards} == {"KASI", "KBSI"}       # KIST 여비규정은 주제 밖
    assert _status(ev)["topic"] == "travel"


def test_topic_with_institution_keeps_both_filters(fake_search, fake_expand):
    conn = FakeConn(topics={"travel": [KASI_TRAVEL, KBSI_TRAVEL]})
    _run(conn, OverviewLLM(), "출장 증빙 제출 절차", {**only("KASI"), "work_ids": [], "topic": "travel"})
    assert fake_search[0]["institution"] == "KASI" and set(fake_search[0]["work_ids"]) == {KASI_TRAVEL, KBSI_TRAVEL}


def test_explicit_regulations_win_over_topic(fake_search, fake_expand):
    conn = FakeConn(topics={"travel": [KASI_TRAVEL, KBSI_TRAVEL]})
    _run(conn, OverviewLLM(), "출장 증빙 제출 절차", {"mode": "all", "institutions": [], "work_ids": [KBSI_TRAVEL],
                                               "topic": "travel"})
    assert all(set(x["work_ids"]) == {KBSI_TRAVEL} for x in fake_search)


def test_unknown_topic_without_table_does_not_filter(fake_search, fake_expand):
    _run(FakeConn(), OverviewLLM(), "출장 증빙 제출 절차", {"mode": "all", "institutions": [], "work_ids": [], "topic": "travel"})
    assert all(x["work_ids"] is None for x in fake_search)


@pytest.mark.parametrize("q", ["천문연 여비규정 27조", "제10조"])
def test_lookup_inside_work_scope(fake_search, q):
    ev = _run(FakeConn(), None, q, {"mode": "all", "institutions": [], "work_ids": [KASI_TRAVEL]})
    assert _status(ev)["intent"] == "lookup" and set(fake_search[0]["work_ids"]) == {KASI_TRAVEL}
