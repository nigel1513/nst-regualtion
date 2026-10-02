from reg.qa.analyze import Analysis
from reg.qa.analyze import analyze
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
    r = generate(llm, "q", Analysis("KASI", None, "정의", None, []), E)  # 기한형이 아니면 코드가 인용을 고치지 않는다
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
    from reg.platform.llm import ProviderError

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


def test_unmatched_extra_citation_is_dropped_when_a_good_one_remains():
    e2 = Evidence("E2", "w", "v", "여비규정", "a4", "제4조", "여비는 일반적인 경로에 의하여 계산한다.", "primary", "2024-01-02")
    ans = {"결론": "미충족", "근거": [{"id": "E1", "인용": "7일 이내에 출장을 확인할 수 있는 증빙서를"},
                                   {"id": "E2", "인용": "전혀 다른 내용의 문장을 지어냄"}],
           "설명": "10일이 지나 7일 기한을 넘겼습니다.", "확인_필요": [], "문의처": "x"}
    v = verify(ans, [E[0], e2], question_numbers={"10"})
    assert v["ok"] and [c["id"] for c in ans["근거"]] == ["E1"] and v["dropped_citations"] == 1


def test_code_verdict_replaces_quote_of_the_deadline_clause_with_source_sentence():
    llm = FakeLLM({**GOOD, "근거": [{"id": "E1", "인용": "출장 다녀오면 일주일 안에 서류 내면 된다고 적혀 있음"}]})
    r = generate(llm, "천문연 출장 10일 지났어요", A, E)
    assert r["verification"]["ok"] and r["answer"]["근거"][0]["인용"] in E[0].text and "7일 이내에" in r["answer"]["근거"][0]["인용"]


# --- M4 최종 리뷰 수정 ---
def ev(i, work, text, title="여비규정", label="제27조", role="primary"):
    return Evidence(f"E{i}", work, f"{work}@2024-01-01", title, "a27", label, text, role, "2024-01-01")


def test_fallback_never_uses_a_deadline_from_another_regulation():
    month = ev(1, "kr/reg/ETRI/보고", "① 연구책임자는 과제 종료 후 1개월 이내에 결과보고서를 제출하여야 한다.", "과제관리지침", "제12조")
    other = ev(2, "kr/reg/ETRI/성과", "① 성과는 종료 후 15일 이내에 등록한다.", "성과창출지원사업 관리지침", "제9조")
    llm = FakeLLM({"결론": "충족", "근거": [{"id": "E1", "인용": "과제 종료 후 1개월 이내에 결과보고서를 제출하여야 한다"}],
                   "설명": "1개월 이내 제출이므로 20일째인 지금은 아직 기한 안입니다.", "확인_필요": [], "문의처": "연구기획부"})
    r = generate(llm, "결과보고서 20일 지났어요", Analysis("ETRI", None, "기한", 20, []), [month, other])
    assert r["answer"]["결론"] == "충족"  # 1개월(≥28일) 안: 다른 규정의 '15일 이내'로 판정하지 않는다
    assert [c["id"] for c in r["answer"]["근거"]] == ["E1"]


def test_several_deadlines_in_a_clause_give_no_code_verdict():
    two = ev(1, "w", "① 여비는 1개월 이내에 정산하고, 증빙서는 5일 이내에 제출한다.")
    assert deadline_verdict(10, [two.text]) is None
    main_except = "① 신청은 7일 이내에 한다. 다만, 해외출장은 30일 이내에 할 수 있다."
    assert deadline_verdict(10, [main_except]) is None


def test_code_verdict_replaces_contradicting_llm_explanation():
    llm = FakeLLM({**GOOD, "결론": "충족", "설명": "아직 기한 내에 있으므로 문제없습니다."})
    r = generate(llm, "천문연 출장 10일 지났어요", A, E)
    a = r["answer"]
    assert a["결론"] == "미충족" and "기한 내에 있" not in a["설명"] and "문제없" not in a["설명"]


def test_align_rejects_negated_or_renumbered_quotes():
    from reg.qa.answer import _align
    text = E[0].text
    assert _align("출장자는 출장 종료일 다음 날을 기점으로 30일 이내에 출장을 확인할 수 있는 증빙서를 제출하여야 한다", text) is None
    assert _align("출장자는 출장 종료일 다음 날을 기점으로 7일 이내에 증빙서를 제출하지 아니하여도 된다", text) is None
    long = "① 가. 여비는 지급한다.\n② 나. 증빙서를 제출하지 아니한 경우 여비를 지급하지 아니한다.\n③ 다. 기타 여비는 지급한다."
    assert _align("제출하지 아니한 경우에도 여비를 지급한다", long) is None


def test_question_number_cannot_pose_as_a_rule_deadline():
    v = verify({**GOOD, "결론": "미충족", "설명": "규정상 20일 이내에 내야 하므로 지금 내면 됩니다."}, E, question_numbers={"20"})
    assert not v["numbers_match"]
    month = ev(1, "w", "① 보고서는 1개월 이내에 제출하며 1회 연장할 수 있다.")
    ok = verify({"결론": "조건부", "근거": [{"id": "E1", "인용": "보고서는 1개월 이내에 제출하며"}],
                 "설명": "보고서는 1개월 이내에 내야 합니다.", "확인_필요": [], "문의처": "x"}, [month], set())
    assert ok["numbers_match"]
    bad = verify({"결론": "조건부", "근거": [{"id": "E1", "인용": "보고서는 1개월 이내에 제출하며"}],
                  "설명": "보고서는 1주일 이내에 내야 합니다.", "확인_필요": [], "문의처": "x"}, [month], set())
    assert not bad["numbers_match"]


def test_align_accepts_an_abridged_quote_within_one_sentence():
    from reg.qa.answer import _align
    text = ("① 출장자는 출장 종료일부터 10일 이내에 승인권자의 결재를 받은 출장복명서를 출장복명 담당부서에 제출하여야 하며, "
            "출장복명 담당부서는 다음 각 호와 같다. 다만, 숙박이 없는 국내출장 시에는 구두복명으로 갈음하며, 당초의 사항에 "
            "변경이 있는 경우에는 사유서를 첨부하여 출장승인권자의 결재를 받아야 한다.")
    span = _align("출장자는 출장 종료일부터 10일 이내에 출장복명서를 제출하여야 한다.", text)
    assert span and span.startswith("출장자는") and "10일 이내" in span and "숙박이 없는" not in span


def test_parse_strips_evidence_id_suffix_from_quote():
    from reg.qa.answer import _parse, _pattern
    out = "결론: 판단불가\n근거: E1\n인용: 이 규정은 인권보호에 관한 사항을 정함 (E1)\n설명: 근거에 반려동물 관련 규정이 없습니다.\n확인: 없음\n문의처: 총무팀"
    assert _parse(out, _pattern(["E1"]))["근거"][0]["인용"] == "이 규정은 인권보호에 관한 사항을 정함"


def test_month_deadline_is_judged_only_when_certain():
    t = ["연구개발과제 종료 후 1개월 이내에 결과보고서를 제출하여야 한다."]
    assert deadline_verdict(20, t) == ("충족", "1개월")
    assert deadline_verdict(40, t) == ("미충족", "1개월")
    assert deadline_verdict(30, t) == ("조건부", "1개월")  # 달에 따라 28~31일


def test_elapsed_days_from_two_calendar_dates():
    a = analyze(None, "출장이 9월 20일에 끝났고 오늘이 9월 25일이에요")
    assert a.elapsed_days == 5 and a.question_type == "기한"
