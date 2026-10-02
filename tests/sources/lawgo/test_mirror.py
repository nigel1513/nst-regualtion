from datetime import date
from pathlib import Path

from reg.core.model import Prov
from reg.sources.lawgo.mirror import catalog_row, mark_abolished, record_annexes, store_annex_body, upsert_catalog
from reg.sources.lawgo.xml import AdmrulRow, AnnexRow
from tests.sources.lawgo.helpers import load_reg, mirror_admrul, mirror_law

FX = Path(__file__).parent / "fixtures"
V1 = {1: ("목적", "이 영은 여비를 정한다."), 2: ("정의", "이 영에서 쓰는 용어는 다음과 같다."),
      3: ("구분", "여비는 다음과 같이 구분한다.")}
V2 = {1: ("목적", "이 영은 여비를 정한다."), 2: ("정의", "이 영에서 쓰는 용어의 뜻은 다음과 같다."),
      4: ("신설", "새 조문이다.")}


def _art(c, law_id, path):
    return c.execute("SELECT * FROM law.article WHERE law_id = %s AND path = %s", (law_id, path)).fetchone()


def test_first_load_writes_master_version_articles(lconn, blob):
    st = mirror_law(lconn, blob, "009402", "공무원 여비 규정", V1, "1001")
    assert st == {"articles": 3, "added": 0, "modified": 0, "deleted": 0, "kept_cited": 0}
    m = lconn.execute("SELECT * FROM law.law_master WHERE law_id = '009402'").fetchone()
    assert (m["current_mst"], m["status"], m["name_norm"], m["family"]) == ("1001", "현행", "공무원여비규정", "law")
    assert m["url"] == "https://www.law.go.kr/법령/공무원%20여비%20규정"
    v = lconn.execute("SELECT * FROM law.law_version WHERE mst = '1001'").fetchone()
    assert v["is_current"] and v["articles_loaded"] and v["promulgation_no"] == "100"
    assert v["effective_on"] == date(2026, 6, 30) and v["revision_kind"] == "일부개정"
    assert v["xml_url"] == "https://www.law.go.kr/DRF/lawService.do?target=law&MST=1001&type=XML"
    a1 = _art(lconn, "009402", "a1")
    assert (a1["jo_code"], a1["label"], a1["heading"], a1["unit"]) == ("000100", "제1조", "목적", "article")
    assert a1["url"] == "https://www.law.go.kr/법령/공무원%20여비%20규정/제1조"
    log = lconn.execute("SELECT path, change FROM law.change_log").fetchall()
    assert [(r["path"], r["change"]) for r in log] == [(None, "law_added")]


def test_new_version_replaces_articles_keeps_past_metadata_and_logs_changes(lconn, blob):
    mirror_law(lconn, blob, "009402", "공무원 여비 규정", V1, "1001")
    a1_id = _art(lconn, "009402", "a1")["id"]
    st = mirror_law(lconn, blob, "009402", "공무원 여비 규정", V2, "1002", on="20261001", no="101")
    assert (st["added"], st["modified"], st["deleted"]) == (1, 1, 1)
    vers = lconn.execute("SELECT mst, is_current, promulgation_no, effective_on FROM law.law_version ORDER BY mst").fetchall()
    assert [(v["mst"], v["is_current"], v["promulgation_no"]) for v in vers] == [("1001", False, "100"),
                                                                                  ("1002", True, "101")]
    assert vers[0]["effective_on"] == date(2026, 6, 30)  # 지난 판본은 판본 정보만 남는다
    paths = {r["path"] for r in lconn.execute("SELECT path FROM law.article WHERE law_id = '009402'").fetchall()}
    assert paths == {"a1", "a2", "a4"}  # 인용 없는 a3는 지운다
    a1 = _art(lconn, "009402", "a1")
    assert a1["id"] == a1_id and a1["mst"] == "1002"  # id가 판본을 넘어 유지된다
    log = lconn.execute("SELECT path, change FROM law.change_log WHERE to_mst = '1002' ORDER BY path").fetchall()
    assert [(r["path"], r["change"]) for r in log] == [("a2", "modified"), ("a3", "deleted"), ("a4", "added")]


def test_cited_article_is_kept_when_it_disappears(lconn, blob):
    mirror_law(lconn, blob, "009402", "공무원 여비 규정", V1, "1001")
    load_reg(lconn, blob, "kr/reg/KASI/여비규정", "여비규정",
             [Prov("a1", "article", "제1조", "목적", "「공무원 여비 규정」 제3조에 따른다.")])
    a3 = _art(lconn, "009402", "a3")["id"]
    lconn.execute("UPDATE regulation.reference SET target_law_id = '009402', target_law_article_id = %s", (a3,))
    assert mirror_law(lconn, blob, "009402", "공무원 여비 규정", V2, "1002")["kept_cited"] == 1
    assert _art(lconn, "009402", "a3")["gone_in_mst"] == "1002"
    mirror_law(lconn, blob, "009402", "공무원 여비 규정", {**V2, 4: ("신설", "바뀐 조문이다.")}, "1003")
    assert _art(lconn, "009402", "a3")["gone_in_mst"] == "1002"  # 처음 사라진 판본을 유지한다
    assert lconn.execute("SELECT target_law_article_id FROM regulation.reference").fetchone()["target_law_article_id"] == a3


def test_article_emptied_to_deleted_is_logged_as_deleted(lconn, blob):
    mirror_law(lconn, blob, "009402", "공무원 여비 규정", V1, "1001")
    mirror_law(lconn, blob, "009402", "공무원 여비 규정", {**V1, 3: ("구분", "삭제 <2026. 10. 1.>")}, "1002")
    assert _art(lconn, "009402", "a3")["deleted"] is True
    log = lconn.execute("SELECT path, change FROM law.change_log WHERE to_mst = '1002'").fetchall()
    assert [(r["path"], r["change"]) for r in log] == [("a3", "deleted")]


def test_same_version_twice_is_skipped(lconn, blob):
    mirror_law(lconn, blob, "009402", "공무원 여비 규정", V1, "1001")
    assert mirror_law(lconn, blob, "009402", "공무원 여비 규정", V1, "1001") == {"skipped": 1}
    assert lconn.execute("SELECT count(*) AS n FROM law.change_log").fetchone()["n"] == 1


def test_abolish_then_reappear(lconn, blob):
    mirror_law(lconn, blob, "009402", "공무원 여비 규정", V1, "1001")
    assert mark_abolished(lconn, "009402") is True and mark_abolished(lconn, "009402") is False
    m = lconn.execute("SELECT status, missing_since FROM law.law_master WHERE law_id = '009402'").fetchone()
    assert m["status"] == "폐지" and m["missing_since"] is not None
    assert lconn.execute("SELECT count(*) AS n FROM law.change_log WHERE change = 'law_abolished'").fetchone()["n"] == 1
    mirror_law(lconn, blob, "009402", "공무원 여비 규정", V2, "1002")
    m = lconn.execute("SELECT status, missing_since FROM law.law_master WHERE law_id = '009402'").fetchone()
    assert m["status"] == "현행" and m["missing_since"] is None


def test_record_annexes_upserts_retires_and_stores_bodies(lconn, blob):
    mirror_law(lconn, blob, "009402", "공무원 여비 규정", V1, "1001")

    def a(seq, title):
        return AnnexRow(seq, "law", "1001", "009402", "공무원 여비 규정", "000100", "별표", title, date(2026, 6, 30),
                        "/LSW/flDownload.do?flSeq=1", "/LSW/flDownload.do?flSeq=2")

    assert record_annexes(lconn, "009402", "law", [a("11", "국내 여비"), a("12", "국외 여비")]) == 2
    assert record_annexes(lconn, "009402", "law", [a("11", "국내 여비 지급표")]) == 0
    rows = {r["seq"]: r for r in lconn.execute("SELECT * FROM law.annex").fetchall()}
    assert rows["11"]["title"] == "국내 여비 지급표" and rows["11"]["is_current"] and not rows["12"]["is_current"]
    assert rows["11"]["view_url"] == "https://www.law.go.kr/LSW/lsBylInfoP.do?bylSeq=11&lsiSeq=1001"
    store_annex_body(lconn, blob, "11", b"<html>x</html>", b"%PDF-1.4")
    r = lconn.execute("SELECT html_key, pdf_key, fetched_at FROM law.annex WHERE seq = '11'").fetchone()
    assert (r["html_key"], r["pdf_key"]) == ("law/annex/11.html", "law/annex/11.pdf") and r["fetched_at"]
    assert blob.get("law/annex/11.pdf") == b"%PDF-1.4"


def test_catalog_prefers_current_rows(lconn):
    def row(seq, status, no):
        return AdmrulRow(seq, "75386", "국가연구개발사업 연구개발비 사용 기준", "고시", "과학기술정보통신부",
                         date(2026, 5, 6), no, date(2026, 5, 6), "일부개정", status)

    for rows in ([row("200", "현행", "2026-38"), row("199", "연혁", "2026-1")],
                 [row("199", "연혁", "2026-1"), row("200", "현행", "2026-38")]):
        upsert_catalog(lconn, rows)
        c = catalog_row(lconn, "75386")
        assert (c.seq, c.status, c.issue_no) == ("200", "현행", "2026-38")


def test_admrul_version_from_recorded_fixture(lconn, blob):
    st = mirror_admrul(lconn, blob, (FX / "admrul_2100000285346.xml").read_bytes(), "2100000285346")
    assert st["articles"] > 30
    m = lconn.execute("SELECT * FROM law.law_master WHERE law_id = 'admrul:75610'").fetchone()
    assert (m["family"], m["kind"], m["source_id"]) == ("admrul", "훈령", "75610")
    assert m["url"] == "https://www.law.go.kr/행정규칙/영장심의위원회%20운영세칙"
    assert _art(lconn, "admrul:75610", "a3.p2") is not None
    assert _art(lconn, "admrul:75610", "a2")["url"].endswith("/행정규칙/영장심의위원회%20운영세칙/제2조")
