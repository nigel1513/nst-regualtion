"""답변 방식 (assistant-scope): 기본은 일반 답변(결론 없음). 자기 상황을 말하고 괜찮은지·가능한지를 물을 때만 판정."""
import pytest

from reg.platform.llm import ProviderError
from reg.qa.analyze import analyze, answer_mode
from reg.qa.answer import explain
from reg.qa.evidence import Evidence

GENERAL = [
    "콜로키움 규정이 뭐야?",
    "출장 증빙은 언제까지 내야 해?",
    "연구장비 구매 절차 알려줘",
    "유연근무 신청은 누가 승인해?",
    "숙박비 상한이 얼마야?",
    "증빙 기한은?",
    "한국전자통신연구원 출장복명서 제출 기한이 며칠인가요?",
    "연구회 직원이 수해를 입으면 재해구호휴가를 며칠 받을 수 있나요?",     # 가정(입으면)이지 자기 상황이 아니다
    "연차휴가 사용 촉구를 받으면 며칠 안에 사용 시기를 정해야 하나요?",
    "연구노트는 어떻게 작성하나요?",
    "출장 증빙 기한을 넘기면 어떻게 되나요?",
    "연구회 사무실 커피머신 사용 규칙이 있나요?",
    "KASI 콜로키움 운영위원회는 무슨 일을 해?",
    "퇴직금은 어떻게 계산하나요",
    "국외출장 결과보고서 제출 대상은?",
]
JUDGMENT = [
    "출장 다녀온 지 10일 지났는데 증빙 안 냈어요. 괜찮나요?",
    "천문연 소속인데 출장 다녀온 지 10일 지났고 지출결의를 아직 안 했어요. 문제가 없을까요?",
    "한국천문연구원 직원입니다. 출장 끝나고 5일 지났는데 아직 증빙서를 안 냈어요.",
    "연구회 국외출장 출장복명서는 언제까지 내야 하나요? 다녀온 지 2주 지났어요.",
    "KIST 출장 중 숙박비 상한을 넘겨 썼는데 여행 끝나고 10일 지났어요. 정산 신청 가능한가요?",
    "키스트 해외출장 중 숙박비를 초과 지출했고 여행 끝난 지 5일 지났어요.",
    "천문연 국외출장 결과보고서를 귀임 후 20일이 지났는데 아직 안 냈어요.",
    "천문연 직원이 반려동물을 데리고 출근해도 되나요?",
    "출장비로 30만원을 썼는데 정산 받을 수 있나요?",
    "법인카드로 회식비를 결제했는데 위반인가요?",
    "다음 주에 휴가를 5일 연속 쓰려고 하는데 가능한가요?",
    "NST 국내출장 마친 지 12일 지났는데 정산 신청을 못 했습니다. 괜찮나요?",
]


@pytest.mark.parametrize("q", GENERAL)
def test_general_by_rules(q):
    assert answer_mode(q) == "general"


@pytest.mark.parametrize("q", JUDGMENT)
def test_judgment_by_rules(q):
    a = analyze(None, q)
    assert answer_mode(q, a.elapsed_days) == "judgment" and a.mode == "judgment"


class TieLLM:
    def __init__(self, out="판단", fail=False):
        self.out, self.fail, self.calls = out, fail, []

    def regex(self, messages, pattern, **kw):
        self.calls.append(pattern)
        if self.fail:
            raise ProviderError("down")
        if pattern.startswith("유형"):
            return "유형: 가능여부\n검색어: 겸직"
        return self.out


def test_unclear_asks_llm_once_and_defaults_to_general():
    q = "겸직 허가 없이 외부 강의를 하면 징계를 받나요?"         # 상황인지 일반 물음인지 규칙으로는 모른다
    llm = TieLLM("판단")
    assert answer_mode(q, llm=llm) == "judgment" and len(llm.calls) == 1
    assert answer_mode(q, llm=TieLLM("일반")) == "general"
    assert answer_mode(q, llm=TieLLM(fail=True)) == "general"
    assert answer_mode(q) == "general"                      # LLM 없으면 일반
    assert analyze(TieLLM("판단"), q).mode == "judgment"


def test_clear_cases_do_not_call_llm():
    llm = TieLLM()
    for q in GENERAL[:5] + JUDGMENT[:3]:
        answer_mode(q, analyze(None, q).elapsed_days, llm=llm)
    assert llm.calls == []


# ---------------------------------------------------------------- 일반 답변 생성

DEF = ("제2조(정의) 이 기준에서 사용하는 용어의 뜻은 다음과 같다.\n1. “KASI 콜로키움”(이하 “콜로키움”이라 한다)이란 연구원 소속 "
       "임직원의 연구 역량 강화와 연구 교류 확대를 위해 콜로키움 위원회에서 주관하는 세미나 또는 토론회를 의미한다.")
EV = [Evidence("E1", "kr/reg/KASI/KASI콜로키움운영기준", "v1", "KASI 콜로키움 운영 기준", "a2", "제2조(정의)", DEF, "primary",
               None)]


class ExplainLLM:
    def __init__(self, *outs):
        self.outs, self.calls = list(outs), []

    def regex(self, messages, pattern, **kw):
        self.calls.append(messages)
        assert pattern.startswith("설명")
        return self.outs.pop(0)


def _a(q="콜로키움 규정이 뭐야?"):
    return analyze(None, q)


def test_explain_answers_without_verdict_and_keeps_verbatim_quote():
    llm = ExplainLLM("설명: KASI 콜로키움은 연구 역량 강화와 연구 교류 확대를 위해 콜로키움 위원회가 주관하는 세미나나 토론회입니다 (E1). "
                     "이 기준은 그 운영을 정합니다.\n근거: E1\n인용: 콜로키움 위원회에서 주관하는 세미나 또는 토론회를 의미한다.")
    g = explain(llm, "콜로키움 규정이 뭐야?", _a(), EV)
    ans = g["answer"]
    assert ans["결론"] is None and g["verdict_source"] is None and g["verification"]["ok"]
    assert "E1" not in ans["설명"] and ans["설명"].startswith("KASI 콜로키움은")
    assert len(ans["근거"]) == 1 and ans["근거"][0]["id"] == "E1"           # 설명 첫 문장을 받치는 원문 문장 전체로 넓힌다
    assert ans["근거"][0]["인용"] in DEF and ans["근거"][0]["인용"].endswith("콜로키움 위원회에서 주관하는 세미나 또는 토론회를 의미한다.")
    sys_prompt = llm.calls[0][0]["content"]
    assert "판정" in sys_prompt and "2~4문장" in sys_prompt


def test_explain_replaces_paraphrased_quote_with_closest_source_sentence():
    llm = ExplainLLM("설명: 콜로키움은 연구원 임직원의 연구 교류를 위한 세미나 또는 토론회입니다.\n근거: E1\n"
                     "인용: 콜로키움이란 연구원 임직원의 연구 역량 강화와 교류 확대를 위해 위원회가 주관하는 세미나를 뜻한다.")
    ans = explain(llm, "콜로키움이 뭐야?", _a("콜로키움이 뭐야?"), EV)["answer"]
    assert ans and ans["근거"][0]["인용"] in DEF


def test_explain_retries_on_invented_number_then_gives_up():
    bad = "설명: 콜로키움은 매년 12회 열리는 세미나입니다.\n근거: E1\n인용: 콜로키움 위원회에서 주관하는 세미나 또는 토론회를 의미한다."
    llm = ExplainLLM(bad, bad)
    g = explain(llm, "콜로키움이 뭐야?", _a("콜로키움이 뭐야?"), EV)
    assert g["answer"] is None and len(llm.calls) == 2 and "number" in g["verification"]["problems"]
    assert "이전 답변의 문제" in llm.calls[1][1]["content"]


def test_explain_may_state_the_effective_date_shown_with_the_evidence():
    ev = [Evidence(**{**EV[0].__dict__, "effective_from": "2023-08-01"})]
    llm = ExplainLLM("설명: KASI 콜로키움은 콜로키움 위원회가 주관하는 세미나 또는 토론회이며, 이 기준은 2023년 8월 1일부터 "
                     "시행되었습니다.\n근거: E1\n인용: 콜로키움 위원회에서 주관하는 세미나 또는 토론회를 의미한다.")
    g = explain(llm, "콜로키움 규정이 뭐야?", _a(), ev)
    assert g["answer"] and len(llm.calls) == 1
    assert "시행일" in llm.calls[0][0]["content"]


def test_explain_adds_source_sentence_for_explanation_sentences_without_a_quote():
    ev = EV + [Evidence("E2", "kr/reg/KASI/KASI콜로키움운영기준", "v1", "KASI 콜로키움 운영 기준", "a10", "제10조(운영 예산)",
                        "제10조(콜로키움 운영 예산) 콜로키움 운영 예산은 다과비, 회의비, 연사료로 구성한다.", "primary", None)]
    llm = ExplainLLM("설명: KASI 콜로키움은 콜로키움 위원회가 주관하는 세미나 또는 토론회입니다. 운영 예산은 다과비, 회의비, 연사료로 "
                     "구성됩니다.\n근거: E1\n인용: 콜로키움 위원회에서 주관하는 세미나 또는 토론회를 의미한다.")
    ans = explain(llm, "콜로키움 규정이 뭐야?", _a(), ev)["answer"]
    assert [c["id"] for c in ans["근거"]] == ["E1", "E2"]
    assert ans["근거"][1]["인용"] in ev[1].text and "다과비" in ans["근거"][1]["인용"]


def test_explain_does_not_add_weak_matches():
    llm = ExplainLLM("설명: KASI 콜로키움은 콜로키움 위원회가 주관하는 세미나 또는 토론회입니다. 자세한 내용은 담당 부서에 물어보세요."
                     "\n근거: E1\n인용: 콜로키움 위원회에서 주관하는 세미나 또는 토론회를 의미한다.")
    ans = explain(llm, "콜로키움 규정이 뭐야?", _a(), EV)["answer"]
    assert [c["id"] for c in ans["근거"]] == ["E1"]
