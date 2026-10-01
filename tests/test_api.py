from datetime import date
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from reg.api.app import create_app
from reg.process import process_once
from reg.storage.blob import LocalBlobStore
from tests.test_process import seed_alio

S = Path(__file__).parent / "fixtures" / "samples"
WID = "kr/reg/KASI/여비규정"


@pytest.fixture
def api(conn, migrated, tmp_path):
    blob = LocalBlobStore(tmp_path)
    seed_alio(conn, blob, (S / "kasi-yeobi-339.pdf").read_bytes())
    process_once(conn, blob, today=date(2026, 10, 2))
    with TestClient(create_app(migrated[0], blob)) as c:
        yield c


def test_institutions_and_works(api):
    inst = api.get("/api/v1/institutions").json()
    assert {"code": "KASI", "name": "한국천문연구원", "kind": "GRI", "works": 1} in inst
    works = api.get("/api/v1/works", params={"institution": "KASI"}).json()
    assert works[0]["id"] == WID and works[0]["version"]["effective_from"] == "2024-01-17"
    assert api.get("/api/v1/works", params={"q": "여비"}).json()[0]["id"] == WID


def test_view_current_with_refs_and_unicode_id(api):
    r = api.get(f"/api/v1/work/view?id={quote(WID, safe='')}")
    assert r.status_code == 200
    v = r.json()
    assert v["work"]["title"] == "여비규정" and v["version"]["version_state"] == "CURRENT"
    p = {x["path"]: x for x in v["provisions"]}
    assert "7일 이내에" in p["a27.p1"]["text"] and p["a27"]["anchor"]["page"] == 12
    refs = v["refs"][str(p["a27.p3"]["id"])]
    assert any(x["rel_type"] == "EXCEPTION" and x["target_path"] == "a27.p1" for x in refs)
    assert v["history"][-1]["number"] == "339" and v["version"]["source"]["has_view"] is True


def test_as_of_before_first_version_is_404(api):
    r = api.get("/api/v1/work/view", params={"id": WID, "as_of": "1990-01-01"})
    assert r.status_code == 404 and "시행 중인 버전이 없습니다" in r.json()["detail"]


def test_versions_and_files(api):
    vs = api.get("/api/v1/work/versions", params={"id": WID}).json()
    assert vs[0]["effective_from"] == "2024-01-17"
    f = api.get("/api/v1/file", params={"version": vs[0]["id"], "kind": "view"})
    assert f.status_code == 200 and f.content.startswith(b"%PDF") and f.headers["content-type"] == "application/pdf"
    o = api.get("/api/v1/file", params={"version": vs[0]["id"], "kind": "original"})
    assert "filename*=UTF-8''" in o.headers["content-disposition"]


def test_unknown_work_404(api):
    assert api.get("/api/v1/work/view", params={"id": "kr/reg/NONE/x"}).status_code == 404
