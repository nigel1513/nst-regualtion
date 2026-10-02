from reg.qa.evaluate import run_eval


def test_run_eval_scores_cases(monkeypatch):
    from reg.qa import evaluate as E

    answers = iter([
        {"status": "answered", "institution": "KASI", "evidence": [{"work_id": "kr/reg/KASI/여비규정", "path": "a27"}],
         "answer": {"결론": "미충족", "근거": [{"id": "E1"}]}, "id": 1},
        {"status": "need_institution", "institution": None, "evidence": [], "answer": None, "id": 2},
    ])
    monkeypatch.setattr(E, "ask", lambda *a, **k: next(answers))
    cases = [{"id": "k1", "question": "q", "expect": {"status": "answered", "work_contains": "여비", "article": "a27",
                                                     "verdict": "미충족"}},
             {"id": "n1", "question": "q", "expect": {"status": "need_institution"}}]
    r = run_eval(None, {}, cases)
    assert r["status_acc"] == 1.0 and r["citation_hit"] == 1.0 and r["verdict_acc"] == 1.0
    assert r["need_institution_acc"] == 1.0 and len(r["cases"]) == 2


def test_expect_status_may_list_alternatives(monkeypatch):
    from reg.qa import evaluate as E

    monkeypatch.setattr(E, "ask", lambda *a, **k: {"status": "answered", "institution": "NST", "evidence": [],
                                                    "answer": {"결론": "판단불가", "근거": [{"id": "E1"}]}, "id": 3})
    r = run_eval(None, {}, [{"id": "x", "question": "q", "expect": {"status": ["not_found", "answered"], "verdict": "판단불가"}}])
    assert r["status_acc"] == 1.0 and r["verdict_acc"] == 1.0


def test_citation_metric_uses_the_answer_citations_and_reports_checks(monkeypatch):
    from reg.qa import evaluate as E

    monkeypatch.setattr(E, "ask", lambda *a, **k: {
        "status": "answered", "institution": "KASI",
        "evidence": [{"id": "E1", "work_id": "kr/reg/KASI/여비규정", "path": "a27"},
                     {"id": "E2", "work_id": "kr/reg/KASI/여비규정", "path": "a4"}],
        "answer": {"결론": "미충족", "근거": [{"id": "E2"}]},
        "verification": {"numbers_match": True, "consistent": False}, "id": 4})
    r = run_eval(None, {}, [{"id": "x", "question": "q", "expect": {"status": "answered", "work_contains": "여비",
                                                                     "article": "a27"}}])
    assert r["retrieval_hit"] == 1.0 and r["citation_hit"] == 0.0  # 근거에는 있었지만 답변은 a4를 인용
    assert r["numbers_rate"] == 1.0 and r["consistency_rate"] == 0.0
