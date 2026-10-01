from datetime import date

from reg.process import process_once
from reg.qa.analyze import analyze
from reg.qa.evidence import expand
from reg.storage.blob import LocalBlobStore
from tests.test_process import FX, seed_alio


class FakeLLM:
    def __init__(self, out=None, fail=False):
        self.out, self.fail, self.calls = out, fail, []

    def json(self, messages, schema, **kw):
        self.calls.append(messages)
        if self.fail:
            from reg.llm import ProviderError
            raise ProviderError("down")
        return self.out


def test_analyze_rules_and_llm_terms():
    llm = FakeLLM({"question_type": "기한", "terms": ["여비 정산", "증빙 제출"]})
    a = analyze(llm, "천문연 소속인데 출장 다녀온 지 10일 지났고 지출결의를 아직 안 했어요")
    assert (a.institution, a.elapsed_days, a.question_type) == ("KASI", 10, "기한")
    assert "증빙 제출" in a.terms
    b = analyze(FakeLLM(fail=True), "2023년 3월 5일 기준으로 2주 지났는데 괜찮나요")
    assert (b.as_of, b.elapsed_days, b.question_type) == ("2023-03-05", 14, "기한")  # 경과 기간이 있으면 기한형


def test_expand_article_with_exception_and_citation(conn, tmp_path):
    blob = LocalBlobStore(tmp_path)
    seed_alio(conn, blob, (FX / "samples" / "kasi-yeobi-339.pdf").read_bytes())
    process_once(conn, blob, today=date(2026, 10, 2))
    v = conn.execute("SELECT id, work_id, title FROM regulation.work_version").fetchone()
    ev = expand(conn, [{"version_id": v["id"], "work_id": v["work_id"], "title": v["title"], "path": "a27"}])
    assert ev[0].id == "E1" and ev[0].role == "primary" and "7일 이내에" in ev[0].text and ev[0].label.startswith("제27조")
    cited = [e for e in ev if e.role == "cited"]
    assert any(e.path == "a13" for e in cited)  # ③항의 '제13조'
    assert sum(len(e.text) for e in ev) <= 8000


def test_rule_synonyms_expand_terms_even_without_llm_and_days_force_deadline():
    a = analyze(FakeLLM(fail=True), "천문연 출장 다녀온 지 10일 지났고 지출결의를 아직 안 했어요")
    assert {"정산", "증빙서 제출", "여비"} <= set(a.terms)
    b = analyze(FakeLLM({"question_type": "정의", "terms": []}), "NST 국외출장 다녀온 지 3주 지났어요")
    assert b.question_type == "기한" and b.elapsed_days == 21
