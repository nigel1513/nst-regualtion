from reg.qa.analyze import Analysis
from reg.qa.answer import deadline_verdict, generate, verify
from reg.qa.evidence import Evidence
from tests.test_qa_analyze_evidence import FakeLLM

E = [Evidence("E1", "w", "w@2024-01-17", "여비규정", "a27", "제27조(출장증빙의 제출)",
              "① 출장자는 출장 종료일 다음 날을 기점으로 7일 이내에 출장을 확인할 수 있는 증빙서를 회계담당부서에 제출하여야 한다.",
              "primary", "2024-01-17")]
A = Analysis("KASI", None, "기한", 10, ["증빙 제출"])
GOOD = {"결론": "충족", "근거": [{"id": "E1", "인용": "7일 이내에 출장을 확인할 수 있는 증빙서를 회계담당부서에 제출하여야 한다"}],
        "설명": "출장 종료 후 7일 이내에 증빙서를 내야 하는데 10일이 지나 기한을 넘겼습니다.", "확인_필요": [], "문의처": "회계담당부서"}


def test_deadline_verdict():
    assert deadline_verdict(10, ["7일 이내에 제출"]) == ("미충족", 7)
    assert deadline_verdict(5, ["7일 이내에 제출"]) == ("충족", 7)
    assert deadline_verdict(20, ["3주일 이내에 신청"]) == ("충족", 21)
    assert deadline_verdict(None, ["7일 이내"]) is None and deadline_verdict(3, ["즉시"]) is None


def test_verify_detects_bad_citation_quote_and_number():
    v = verify({**GOOD, "결론": "미충족"}, E, question_numbers={"10"})
    assert v["ok"]
    bad = verify({**GOOD, "결론": "미충족", "근거": [{"id": "E9", "인용": "x"}]}, E, question_numbers=set())
    assert not bad["citations_exist"]
    q = verify({**GOOD, "결론": "미충족", "근거": [{"id": "E1", "인용": "14일 이내에 제출"}]}, E, question_numbers={"10"})
    assert not q["quotes_match"]
    n = verify({**GOOD, "결론": "미충족", "설명": "30일 이내에 내야 합니다."}, E, question_numbers={"10"})
    assert not n["numbers_match"]


def test_code_verdict_overrides_llm_and_consistency():
    llm = FakeLLM(GOOD)  # LLM은 '충족'이라 했지만 10일 > 7일
    r = generate(llm, "천문연 출장 10일 지났어요", A, E)
    assert r["answer"]["결론"] == "미충족" and r["verdict_source"] == "code" and r["verification"]["ok"]


def test_regenerates_once_then_gives_up():
    llm = FakeLLM({**GOOD, "근거": [{"id": "E1", "인용": "원문에 없는 문장을 인용함"}]})  # id는 형식이 막으므로 인용 불일치로
    r = generate(llm, "q", A, E)
    assert r["answer"] is None and r["attempts"] == 2 and len(llm.calls) == 2


def test_llm_down():
    r = generate(FakeLLM(fail=True), "q", A, E)
    assert r["answer"] is None and r["verification"]["problems"] == ["llm_unavailable"]


def test_answer_format_restricts_citation_ids_to_given_evidence():
    llm = FakeLLM(GOOD)
    generate(llm, "천문연 출장 10일 지났어요", A, E)
    assert "근거: (E1)" in llm.pattern


def test_code_uses_top_ranked_deadline_clause_when_llm_cites_another():
    e2 = Evidence("E2", "w", "w@2024-01-17", "여비규정", "a4-2", "제4조의2(여비의 정산)",
                  "① 여행 후 여비의 변경이 있는 경우 계정책임자의 결재로 정산할 수 있다.", "primary", "2024-01-17")
    other = {**GOOD, "결론": "조건부", "근거": [{"id": "E2", "인용": "여행 후 여비의 변경이 있는 경우 계정책임자의 결재로 정산할 수 있다"}],
             "설명": "여비 변경이 있으면 결재로 정산합니다."}
    r = generate(FakeLLM(other), "천문연 출장 10일 지났어요", A, [E[0], e2])
    assert r["answer"]["결론"] == "미충족" and r["verdict_source"] == "code"
    assert [c["id"] for c in r["answer"]["근거"]][0] == "E1"


def test_invalid_json_is_reported_as_invalid_output():
    from reg.llm import ProviderError

    class Bad(FakeLLM):
        def regex(self, *a, **k):
            raise ProviderError("LLM 응답이 형식에 맞지 않음")
    r = generate(Bad(), "q", A, E)
    assert r["verification"]["problems"] == ["llm_invalid_output"]


def test_paraphrased_quote_is_replaced_by_the_original_span():
    e = [Evidence("E1", "w", "v", "출장요령", "a11", "제11조(출장복명)",
                  "① 출장자는 출장 종료일부터 10일 이내에 승인권자의 결재를 받은 출장복명서를 출장복명 담당부서에 제출하여야 하며, "
                  "출장복명 담당부서는 다음 각 호와 같다.", "primary", "2024-03-01")]
    ans = {"결론": "미충족", "근거": [{"id": "E1", "인용": "출장자는 출장 종료일부터 10일 이내에 승인권자의 결재를 받은 출장복명서를 제출하여야 한다"}],
           "설명": "12일이 지나 10일 기한을 넘겼습니다.", "확인_필요": [], "문의처": "x"}
    v = verify(ans, e, question_numbers={"12"})
    assert v["quotes_match"] and ans["근거"][0]["인용"] in e[0].text and "출장복명 담당부서에" in ans["근거"][0]["인용"]
    bad = {**ans, "근거": [{"id": "E1", "인용": "연구원은 매년 예산을 편성하여 이사회 승인을 받는다"}]}
    assert not verify(bad, e, question_numbers=set())["quotes_match"]


def test_derived_numbers_and_ok_wording_pass():
    e = [Evidence("E1", "w", "v", "여비규정", "a13-2", "제13조의2(국외여비의 정산 및 지급)",
                  "국외출장자는 출장을 마친 날의 다음날부터 기산하여 3주일 이내에 정산을 신청하여야 한다.", "primary", "2024-01-02")]
    a = Analysis("NST", None, "기한", 28, [])
    r = generate(FakeLLM({"결론": "미충족", "근거": [{"id": "E1", "인용": "3주일 이내에 정산을 신청하여야 한다"}],
                          "설명": "4주(28일)가 지나 3주일(21일) 기한을 넘겼습니다.", "확인_필요": [], "문의처": "회계"}),
                 "NST 국외출장 다녀온 지 4주 지났어요", a, e)
    assert r["verification"]["ok"], r["verification"]
    ok = verify({"결론": "충족", "근거": [{"id": "E1", "인용": "3주일 이내에 정산을 신청하여야 한다"}],
                 "설명": "출장 후 5일 지났지만 아직 기한 안입니다.", "확인_필요": [], "문의처": "x"}, e, {"5"})
    assert ok["consistent"]
