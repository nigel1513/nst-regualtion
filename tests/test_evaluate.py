from reg.evaluate import run_eval


def test_run_eval_scores_cases(monkeypatch):
    from reg import evaluate as E

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
