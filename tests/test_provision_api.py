"""참조 팝업용 조문 조회 (사용자 요청 2026-10-03): 페이지를 옮기지 않고 참조된 조문 전체를 보여주고 대상 항을 음영 표시."""
from tests.test_api import WID, api  # noqa: F401


def test_provision_returns_whole_article_with_target_marked(api):  # noqa: F811
    r = api.get("/api/v1/provision", params={"work": WID, "path": "a27.p1"})
    assert r.status_code == 200
    d = r.json()
    assert d["work_id"] == WID and d["title"] == "여비규정" and d["institution_name"] == "한국천문연구원"
    assert d["article"]["path"] == "a27" and d["article"]["label"].startswith("제27조")
    targets = [x for x in d["lines"] if x["target"]]
    assert [x["path"] for x in targets][0] == "a27.p1" and "7일 이내" in targets[0]["text"]
    assert any(not x["target"] for x in d["lines"])  # 같은 조의 다른 항도 함께 (문맥)
    assert d["href"].endswith("#a27.p1")


def test_provision_whole_article_target_and_errors(api):  # noqa: F811
    d = api.get("/api/v1/provision", params={"work": WID, "path": "a27"}).json()
    assert all(x["target"] for x in d["lines"])
    assert api.get("/api/v1/provision", params={"work": WID, "path": "a999"}).status_code == 404
    assert api.get("/api/v1/provision", params={"work": "kr/reg/X/없음", "path": "a1"}).status_code == 404
