"""규정 도우미 범위 (assistant-scope): 규정·주제 범위는 검색 질의 안의 필터이고, 규정을 고르면 기관도 정해진다."""
import pytest

import tests.test_chat as base
from reg.qa.chat import chat, collect
from tests.test_chat import HITS, FakeConn, OverviewLLM, only

fake_search, fake_expand = base.fake_search, base.fake_expand     # 같은 가짜 검색·근거 확장 픽스처

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


# ---------------------------------------------------------------- 일반 답변 / 판정 (기관 하나)

class ModeLLM:
    """분석 → (일반) 설명·인용 형식 또는 (판정) 결론 형식. 어떤 형식을 받았는지 남긴다."""

    def __init__(self):
        self.patterns = []

    def regex(self, messages, pattern, **kw):
        self.patterns.append(pattern[:2])
        if pattern.startswith("유형"):
            return "유형: 기한\n검색어: 증빙"
        if pattern.startswith("설명"):
            return ("설명: 한국천문연구원 출장자는 출장 후 7일 이내에 증빙서를 제출해야 합니다 (E1).\n"
                    "근거: E1\n인용: 출장자는 출장 후 7일 이내에 증빙서를 제출하여야 한다.")
        assert pattern.startswith("결론")
        return ("결론: 미충족\n근거: E1\n인용: 출장자는 출장 후 7일 이내에 증빙서를 제출하여야 한다.\n"
                "설명: 출장 후 7일 이내에 증빙서를 내야 하는데 10일이 지나 기한을 넘겼습니다.\n확인: 없음\n문의처: 회계담당부서")


def test_general_question_gets_direct_answer_without_verdict(fake_search, fake_expand):
    llm = ModeLLM()
    ev = _run(FakeConn(), llm, "출장 증빙은 언제까지 내야 해?", only("KASI"))
    ans = next(e["data"] for e in ev if e["event"] == "answer")
    assert ans["conclusion"] is None and ans["checks"] == [] and "E1" not in ans["explanation"]
    assert ans["sentences"] and all(s["cites"] == [1] for s in ans["sentences"])
    cites = next(e["data"]["items"] for e in ev if e["event"] == "citations")
    assert cites[0]["quote"] in HITS[0]["text"]
    assert "결론" not in [p[:2] for p in llm.patterns] and ev[-1]["data"]["status"] == "answered"


def test_own_situation_with_ok_question_gets_verdict(fake_search, fake_expand):
    llm = ModeLLM()
    ev = _run(FakeConn(), llm, "출장 다녀온 지 10일 지났는데 증빙 안 냈어요. 괜찮나요?", only("KASI"))
    ans = next(e["data"] for e in ev if e["event"] == "answer")
    assert ans["conclusion"] == "미충족" and "설명" not in llm.patterns


def test_general_question_inside_regulation_scope(fake_search, fake_expand):
    ev = _run(FakeConn(), ModeLLM(), "증빙 기한은?", {"mode": "all", "institutions": [], "work_ids": [KASI_TRAVEL]})
    ans = next(e["data"] for e in ev if e["event"] == "answer")
    assert ans["conclusion"] is None
