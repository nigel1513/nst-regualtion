import pytest

from reg.qa.service import ask
from reg.index.indexer import build_release
from reg.index.os import OpenSearch
from tests.test_indexer import FakeEmbedder
from tests.test_search import FakeReranker


class SeqLLM:
    """질의 분석 → 답변 순서로 다른 JSON을 돌려준다."""
    def __init__(self, answer, fail=False):
        self.answer, self.fail, self.n = answer, fail, 0

    def regex(self, messages, pattern, **kw):
        self.n += 1
        if self.fail:
            from reg.platform.llm import ProviderError
            raise ProviderError("down")
        if pattern.startswith("유형"):
            return "유형: 기한\n검색어: 증빙 제출, 여비 정산"
        c = self.answer["근거"][0]
        return (f"결론: {self.answer['결론']}\n근거: {c['id']}\n인용: {c['인용']}\n설명: {self.answer['설명']}\n"
                f"확인: {'; '.join(self.answer['확인_필요']) or '없음'}\n문의처: {self.answer['문의처']}")


@pytest.fixture
def deps(loaded, os_url):
    os = OpenSearch(os_url)
    build_release(loaded, os, FakeEmbedder(), "fake")
    return {"os": os, "embedder": FakeEmbedder(), "reranker": FakeReranker(), "llm_model": "fake"}


def good(conn):
    return {"결론": "충족", "근거": [{"id": "E1", "인용": "7일 이내에 출장을 확인할 수 있는 증빙서를"}],
            "설명": "출장 종료 다음 날부터 7일 이내에 증빙서를 내야 하는데 10일이 지났습니다.", "확인_필요": ["지출결의 절차"],
            "문의처": "회계담당부서"}


def test_need_institution_without_llm(loaded, deps):
    llm = SeqLLM(None)
    r = ask(loaded, {**deps, "llm": llm}, "출장 다녀온 지 10일 지났는데 괜찮나요?")
    assert r["status"] == "need_institution" and {"code": "KASI", "name": "한국천문연구원"} in r["options"]
    assert llm.n == 0


def test_conflicting_institutions_ask_back(loaded, deps):
    r = ask(loaded, {**deps, "llm": SeqLLM(None)}, "천문연 출장 10일 지났어요", user_institution="NST")
    assert r["status"] == "need_institution"


def test_answered_with_code_verdict_and_log(loaded, deps):
    r = ask(loaded, {**deps, "llm": SeqLLM(good(loaded))},
            "천문연 소속인데 출장 다녀온 지 10일 지났고 지출결의를 아직 안 했어요. 연락처 010-1234-5678")
    assert r["status"] == "answered" and r["answer"]["결론"] == "미충족" and r["verdict_source"] == "code"
    assert r["evidence"][0]["path"] == "a27" and r["institution"] == "KASI"
    log = loaded.execute("SELECT question, status, verdict FROM ops.qa_log WHERE id = %s", (r["id"],)).fetchone()
    assert "5678" not in log["question"] and log["status"] == "answered" and log["verdict"] == "미충족"


def test_llm_down_gives_evidence_only(loaded, deps):
    r = ask(loaded, {**deps, "llm": SeqLLM(None, fail=True)}, "천문연 출장 증빙 제출 기한이 며칠인가요")
    assert r["status"] == "evidence_only" and r["evidence"] and r["answer"] is None


class CountingPool:
    """연결 대여 수를 센다: LLM 호출 중에는 DB 연결을 잡고 있지 않아야 한다 (API 풀 고갈 방지)."""
    def __init__(self, conn):
        self.conn, self.out = conn, 0

    def connection(self):
        from contextlib import contextmanager

        @contextmanager
        def cm():
            self.out += 1
            try:
                yield self.conn
            finally:
                self.out -= 1
        return cm()


def test_db_connection_is_not_held_during_llm_calls(loaded, deps):
    pool = CountingPool(loaded)
    held = []

    class Watch(SeqLLM):
        def regex(self, messages, pattern, **kw):
            held.append(pool.out)
            return super().regex(messages, pattern, **kw)

    r = ask(pool, {**deps, "llm": Watch(good(loaded))}, "천문연 출장 10일 지났어요")
    assert r["status"] == "answered" and held and set(held) == {0}


def test_evidence_carries_matched_paragraph(loaded, deps):
    r = ask(loaded, {**deps, "llm": SeqLLM(good(loaded))}, "천문연 출장 다녀온 지 10일 지났는데 증빙서를 안 냈어요")
    e = r["evidence"][0]
    assert e["path"] == "a27" and "a27.p1" in e["matched_paths"]


def test_citation_question_puts_cited_article_first(loaded, deps):
    r = ask(loaded, {**deps, "llm": SeqLLM(None, fail=True)}, "천문연 여비규정 제3조의3 제2항에 따르면 출장 증빙 기한은?")
    assert r["evidence"][0]["path"] == "a3-3" and r["evidence"][0]["matched_paths"] == ["a3-3.p2"]


def test_ask_without_log_writes_nothing(loaded, deps):
    before = loaded.execute("SELECT count(*) AS n FROM ops.qa_log").fetchone()["n"]
    r = ask(loaded, {**deps, "llm": SeqLLM(good(loaded))}, "천문연 출장 10일 지났는데 증빙서를 안 냈어요", log=False)
    assert r["id"] is None and r["retrieved"][0]["path"].startswith("a27")
    assert loaded.execute("SELECT count(*) AS n FROM ops.qa_log").fetchone()["n"] == before


def test_prompt_names_matched_paragraph():
    from reg.qa.analyze import Analysis
    from reg.qa.answer import _prompt
    from reg.qa.evidence import Evidence

    e = Evidence("E1", "w", "v", "여비규정", "a27", "제27조(출장증빙의 제출)", "① 7일 이내", "primary", None, None,
                 ["a27.p1", "a27.p2.i3"])
    user = _prompt("q", Analysis("KASI", None, "기한", 10), [e], None)[1]["content"]
    assert "질문과 맞는 부분: 제1항, 제2항 제3호" in user


class GeneralLLM(SeqLLM):
    """일반 답변 형식(설명·근거·인용)으로 답한다. 판정 형식(결론)을 받으면 실패시킨다."""
    def __init__(self):
        super().__init__(None)
        self.patterns = []

    def regex(self, messages, pattern, **kw):
        self.patterns.append(pattern[:2])
        if pattern.startswith("유형"):
            return "유형: 기한\n검색어: 증빙 제출"
        assert pattern.startswith("설명"), pattern
        return ("설명: 출장자는 출장을 마친 다음 날부터 7일 이내에 증빙서를 회계담당부서에 제출해야 합니다.\n"
                "근거: E1\n인용: 7일 이내에 출장을 확인할 수 있는 증빙서를")


def test_general_question_answers_without_verdict(loaded, deps):
    llm = GeneralLLM()
    r = ask(loaded, {**deps, "llm": llm}, "천문연 출장 증빙 제출 기한이 며칠인가요?")
    assert r["status"] == "answered" and r["answer"]["결론"] is None and r["verdict_source"] is None
    assert r["verification"]["ok"] and r["verification"]["mode"] == "general" and r["answer_mode"] == "general"
    assert r["evidence"][0]["path"] == "a27" and r["answer"]["근거"][0]["id"] == "E1"
    log = loaded.execute("SELECT status, verdict FROM ops.qa_log WHERE id = %s", (r["id"],)).fetchone()
    assert log["status"] == "answered" and log["verdict"] is None
