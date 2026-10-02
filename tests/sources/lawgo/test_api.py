from datetime import date

import pytest
from fastapi.testclient import TestClient

from reg.api.app import create_app
from reg.core.model import Prov
from reg.sources.lawgo.api import edition_line, sanitize_html
from reg.sources.lawgo.link import link_all
from reg.sources.lawgo.mirror import record_annexes, store_annex_body
from reg.sources.lawgo.xml import AnnexRow
from tests.sources.lawgo.helpers import load_reg, mirror_law

WID = "kr/reg/KASI/여비규정"
YEOBI = {1: ("목적", "이 영은 여비를 정한다."), 10: ("국내 여비", "국내 여비는 다음과 같다.", ["철도운임", "선박운임"])}


def _annex(seq, number, title, file_path, pdf_path):
    return AnnexRow(seq, "law", "1001", "009402", "공무원 여비 규정", number, "별표", title, None, file_path, pdf_path)


@pytest.fixture
def api(lconn, migrated, blob):
    mirror_law(lconn, blob, "009402", "공무원 여비 규정", {1: ("목적", "옛 목적")}, "1000", on="20250101", no="99")
    mirror_law(lconn, blob, "009402", "공무원 여비 규정", YEOBI, "1001")
    load_reg(lconn, blob, WID, "여비규정",
             [Prov("a5", "article", "제5조", "여비", "「공무원 여비 규정」 제10조제1항에 따른다.")])
    link_all(lconn)
    record_annexes(lconn, "009402", "law", [
        _annex("18272187", "000100", "여비 지급 구분표(제3조 관련)", "/LSW/flDownload.do?flSeq=1",
               "/LSW/flDownload.do?flSeq=2"),
        _annex("18272189", "000200", "국내 여비 지급표", None, None)])
    store_annex_body(lconn, blob, "18272187",
                     '<html><body onload="steal()"><script>alert(1)</script><p>별표 1</p></body></html>'.encode(),
                     b"%PDF-1.4 x")
    lconn.commit()
    with TestClient(create_app(migrated[0], blob)) as c:
        yield c, lconn


def test_edition_line_formats():
    assert edition_line({"kind": "법률", "family": "law"},
                        {"promulgation_no": "21421", "promulgated_on": date(2026, 3, 10),
                         "effective_on": date(2026, 9, 11), "revision_kind": "일부개정"}
                        ) == "[시행 2026. 9. 11.] [법률 제21421호, 2026. 3. 10., 일부개정]"
    assert edition_line({"kind": "훈령", "family": "admrul", "ministry": "법무부"},
                        {"promulgation_no": "1624", "promulgated_on": date(2026, 10, 2),
                         "effective_on": date(2026, 10, 2), "revision_kind": "일부개정"}
                        ) == "[시행 2026. 10. 2.] [법무부훈령 제1624호, 2026. 10. 2., 일부개정]"
    assert edition_line({"kind": "대법원규칙", "family": "law"},
                        {"promulgation_no": "03277", "promulgated_on": date(2026, 10, 2),
                         "effective_on": date(2026, 10, 2), "revision_kind": None}
                        ) == "[시행 2026. 10. 2.] [대법원규칙 제3277호, 2026. 10. 2.]"


def test_law_summary_current_version_past_metadata_and_links(api):
    c, _ = api
    d = c.get("/api/v1/law/009402").json()
    assert d["law"]["name"] == "공무원 여비 규정" and d["version"]["mst"] == "1001"
    assert d["version"]["edition_line"] == "[시행 2026. 6. 30.] [대통령령 제100호, 2026. 6. 30., 일부개정]"
    assert [p["mst"] for p in d["past_versions"]] == ["1000"]
    assert d["past_versions"][0]["url"] == "https://www.law.go.kr/법령/공무원%20여비%20규정/(99,20250101)"
    assert d["links"]["law_go"] == "https://www.law.go.kr/법령/공무원%20여비%20규정"
    assert d["links"]["archive"] == "/api/v1/law/version/1001/xml" and "OC=" not in d["links"]["xml"]
    assert d["annex_count"] == 2 and d["work_id"] is None


def test_articles_and_article_detail_with_citing(api):
    c, _ = api
    arts = c.get("/api/v1/law/009402/articles").json()
    assert [a["path"] for a in arts] == ["a1", "a10", "a10.p1", "a10.p2"]
    a10 = next(a for a in arts if a["path"] == "a10")
    d = c.get(f"/api/v1/law/article/{a10['id']}").json()
    assert d["article"]["label"] == "제10조" and [x["path"] for x in d["children"]] == ["a10.p1", "a10.p2"]
    assert d["children"][0]["text"] == "철도운임" and d["law"]["status"] == "현행"
    assert d["links"]["article_go"] == "https://www.law.go.kr/법령/공무원%20여비%20규정/제10조"
    assert d["version"]["edition_line"].startswith("[시행 2026. 6. 30.]")
    assert [(x["work_id"], x["path"], x["institution"]) for x in d["citing"]] == [(WID, "a5", "KASI")]


def test_citations_by_version(api):
    c, conn = api
    vid = conn.execute("SELECT id FROM regulation.work_version WHERE work_id = %s", (WID,)).fetchone()["id"]
    (cites,) = c.get("/api/v1/law/citations", params={"version": vid}).json().values()
    assert cites[0]["law_id"] == "009402" and cites[0]["article_id"] and cites[0]["end"] > cites[0]["start"]


def test_annex_list_and_sandboxed_html(api):
    c, _ = api
    lst = c.get("/api/v1/law/009402/annexes").json()
    assert [(a["seq"], a["has_html"], a["has_pdf"]) for a in lst] == [("18272187", True, True), ("18272189", False, False)]
    assert lst[0]["pdf_url"] == "https://www.law.go.kr/LSW/flDownload.do?flSeq=2"
    r = c.get("/api/v1/law/annex/18272187/html")
    assert r.status_code == 200 and r.headers["content-security-policy"].startswith("sandbox")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "<script" not in r.text.lower() and "onload" not in r.text.lower() and "별표 1" in r.text
    p = c.get("/api/v1/law/annex/18272187/pdf")
    assert p.headers["content-type"] == "application/pdf" and p.content.startswith(b"%PDF")
    assert c.get("/api/v1/law/annex/18272189/html").status_code == 404
    assert c.get("/api/v1/law/annex/18272187").json()["law_name"] == "공무원 여비 규정"


def test_version_archive_and_errors(api):
    c, _ = api
    x = c.get("/api/v1/law/version/1001/xml")
    assert x.status_code == 200 and x.content.lstrip().startswith(b"<?xml")
    assert c.get("/api/v1/law/nope").status_code == 404
    assert c.get("/api/v1/law/nope/articles").status_code == 404
    assert c.get("/api/v1/law/article/999999999").status_code == 404
    assert c.get("/api/v1/law/annex/abc").status_code == 422


def test_sanitize_html_strips_active_content():
    out = sanitize_html(b'<body onload="x()"><script>alert(1)</script><a href="javascript:alert(2)">a</a>'
                        b'<SCRIPT src=x></SCRIPT><meta http-equiv="refresh" content="0;url=e"><div content="ok">t</div></body>')
    assert out == b'<body ><a href="#">a</a><div content="ok">t</div></body>'
