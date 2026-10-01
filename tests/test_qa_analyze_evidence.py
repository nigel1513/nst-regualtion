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

    def regex(self, messages, pattern, **kw):
        """정규식 줄 형식 응답을 흉내낸다: out(dict)을 '키: 값' 줄로 그린다."""
        self.calls.append(messages)
        self.pattern = pattern
        if self.fail:
            from reg.llm import ProviderError
            raise ProviderError("down")
        o = self.out
        if "question_type" in o:
            return f"유형: {o['question_type']}\n검색어: {', '.join(o['terms']) or '없음'}"
        c = o["근거"][0]
        return (f"결론: {o['결론']}\n근거: {c['id']}\n인용: {c['인용']}\n설명: {o['설명']}\n"
                f"확인: {'; '.join(o.get('확인_필요') or []) or '없음'}\n문의처: {o.get('문의처') or '소관부서'}")


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


def test_calendar_dates_are_not_elapsed_days():
    a = analyze(None, "출장이 9월 20일에 끝났고 오늘이 9월 25일이 지났어요")
    assert a.elapsed_days in (None, 5)
    assert analyze(None, "2024년 3월 15일이 지났는데 정산 기한은?").elapsed_days is None
    assert analyze(None, "출장 다녀온 지 10일 지났어요").elapsed_days == 10


def test_cross_work_citation_uses_the_version_valid_at_as_of(conn, tmp_path):
    from reg.collect.archive import store
    from reg.collect.sniff import FileKind
    from reg.load.loader import add_version, rebuild_work, upsert_work
    from reg.qa.evidence import _version_at
    from reg.structure.effective import Effective
    from reg.structure.model import ParsedDoc, Prov

    blob = LocalBlobStore(tmp_path)
    upsert_work(conn, "kr/law/L9", "법률", "가상법", None, {})
    vids = []
    for d, tag in ((date(2020, 1, 1), b"a"), (date(2025, 1, 1), b"b")):
        sid = store(conn, blob, source="alio", url="u", content=b"%PDF" + tag, kind=FileKind("application/pdf", "pdf"),
                    meta={}).id
        vids.append(add_version(conn, "kr/law/L9", sid, ParsedDoc("가상법", None, [], [Prov("a1", "article", "제1조", None, "x")]),
                                Effective(d, "api", "CONFIRMED", d)))
    rebuild_work(conn, "kr/law/L9", date(2026, 10, 2))
    assert _version_at(conn, "kr/law/L9", None) == vids[1]
    assert _version_at(conn, "kr/law/L9", "2023-06-01") == vids[0]
    assert _version_at(conn, "kr/law/L9", "2019-01-01") is None
    assert _version_at(conn, "kr/law/L9", None, release_id="99") is None  # 색인 release 밖의 버전은 쓰지 않는다
