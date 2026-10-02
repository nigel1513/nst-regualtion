from reg.core.model import Prov
from reg.core.refs import resolve_and_store
from reg.sources.lawgo.link import link_all, resolve_name
from reg.sources.lawgo.mirror import mark_abolished
from tests.sources.lawgo.helpers import load_reg, mirror_law

WID = "kr/reg/KASI/여비규정"
YEOBI = {1: ("목적", "이 영은 여비를 정한다."), 3: ("구분", "여비는 구분한다."), 10: ("국내 여비", "국내 여비는 다음과 같다.")}


def _setup(c, blob):
    mirror_law(c, blob, "009402", "공무원 여비 규정", YEOBI, "1001")
    mirror_law(c, blob, "000123", "공공기관의 운영에 관한 법률", {"11-2": ("공시", "공시한다.")}, "2001",
               abbr="공공기관운영법", kind="법률")
    mirror_law(c, blob, "900001", "중복법", {1: ("목적", "가")}, "3001")
    mirror_law(c, blob, "900002", "중복법", {1: ("목적", "나")}, "3002")
    load_reg(c, blob, WID, "여비규정", [
        Prov("a1", "article", "제1조", "목적", "이 규정은 「공무원 여비 규정」 제10조에 따른 여비를 정한다."),
        Prov("a2", "article", "제2조", "준용", "「공공기관운영법」 제11조의2제1항을 준용한다."),
        Prov("a3", "article", "제3조", "기준", "「공무원 여비규정」 제3조에 따른다."),
        Prov("a4", "article", "제4조", "중복", "「중복법」 제1조에 따른다."),
        Prov("a5", "article", "제5조", "모름", "「없는법」 제1조에 따른다.")])


def _refs(c):
    return {r["target_name"]: r for r in c.execute(
        "SELECT target_name, target_law_id, target_law_article_id FROM regulation.reference"
        " WHERE work_id = %s AND target_name IS NOT NULL", (WID,)).fetchall()}


def _aid(c, law_id, path):
    return c.execute("SELECT id FROM law.article WHERE law_id = %s AND path = %s", (law_id, path)).fetchone()["id"]


def _tasks(c):
    return {(t["kind"], t["detail"]["name"], t["detail"].get("reason"), t["status"]) for t in c.execute(
        "SELECT kind, detail, status FROM regulation.review_task WHERE kind LIKE 'REF_LAW%%'").fetchall()}


def test_links_exact_abbreviation_and_normalized_names_to_current_articles(lconn, blob):
    _setup(lconn, blob)
    st = link_all(lconn)
    r = _refs(lconn)
    assert r["공무원 여비 규정"]["target_law_article_id"] == _aid(lconn, "009402", "a10")
    assert r["공공기관운영법"]["target_law_id"] == "000123"
    assert r["공공기관운영법"]["target_law_article_id"] == _aid(lconn, "000123", "a11-2")  # a11-2.p1 → a11-2
    assert r["공무원 여비규정"]["target_law_article_id"] == _aid(lconn, "009402", "a3")
    assert r["중복법"]["target_law_id"] is None and r["없는법"]["target_law_id"] is None
    assert st["ambiguous"] == 1 and st["unmatched"] == 1 and st["linked_article"] == 3
    assert _tasks(lconn) == {("REF_LAW_AMBIGUOUS", "중복법", "multiple", "OPEN")}  # 무매칭은 core REFERENCE가 맡는다


def test_exact_name_beats_another_laws_abbreviation(lconn, blob):
    mirror_law(lconn, blob, "1", "가법", {1: ("목적", "가")}, "11")
    mirror_law(lconn, blob, "2", "나법", {1: ("목적", "나")}, "12", abbr="가법")
    assert resolve_name(lconn, "가법") == ["1"]


def test_single_current_candidate_wins_over_abolished(lconn, blob):
    mirror_law(lconn, blob, "1", "다법", {1: ("목적", "가")}, "11")
    mirror_law(lconn, blob, "2", "다법", {1: ("목적", "나")}, "12")
    mark_abolished(lconn, "1")
    assert resolve_name(lconn, "다 법") == ["2"]


def test_deleted_article_keeps_fk_and_opens_gone_task_idempotently(lconn, blob):
    _setup(lconn, blob)
    link_all(lconn)
    a10 = _aid(lconn, "009402", "a10")
    mirror_law(lconn, blob, "009402", "공무원 여비 규정", {k: v for k, v in YEOBI.items() if k != 10}, "1002")
    st = link_all(lconn)
    assert _refs(lconn)["공무원 여비 규정"]["target_law_article_id"] == a10  # 마지막 판본의 조문을 계속 가리킨다
    assert ("REF_LAW_GONE", "공무원 여비 규정", "article_deleted", "OPEN") in _tasks(lconn)
    n = lconn.execute("SELECT count(*) AS n FROM regulation.review_task").fetchone()["n"]
    st2 = link_all(lconn)
    assert st2["changed"] == 0 and st["gone"] == st2["gone"] == 1
    assert lconn.execute("SELECT count(*) AS n FROM regulation.review_task").fetchone()["n"] == n


def test_abolished_law_and_resolved_tasks_close(lconn, blob):
    _setup(lconn, blob)
    link_all(lconn)
    mark_abolished(lconn, "000123")
    link_all(lconn)
    assert ("REF_LAW_GONE", "공공기관운영법", "law_abolished", "OPEN") in _tasks(lconn)
    lconn.execute("UPDATE law.law_master SET status = '현행' WHERE law_id = '000123'")
    link_all(lconn)
    assert ("REF_LAW_GONE", "공공기관운영법", "law_abolished", "RESOLVED") in _tasks(lconn)


def test_relinks_after_core_reprocess_wipes_references(lconn, blob):
    _setup(lconn, blob)
    link_all(lconn)
    resolve_and_store(lconn, WID)  # core가 다시 처리하면 reference 행을 지우고 새로 만든다
    assert _refs(lconn)["공무원 여비 규정"]["target_law_article_id"] is None
    link_all(lconn)
    assert _refs(lconn)["공무원 여비 규정"]["target_law_article_id"] == _aid(lconn, "009402", "a10")
