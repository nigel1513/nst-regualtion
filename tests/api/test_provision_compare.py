"""규정 보기 → 기관 비교 연결: GET /api/v1/provision/compare?pv= (조항 → 규정·조·주제·이 조를 근거로 한 비교값)."""
import pytest
from fastapi.testclient import TestClient

from reg.api.app import create_app
from reg.platform.storage.blob import LocalBlobStore
from tests.compare.test_api_store import cells, seeded, wid  # noqa: F401


@pytest.fixture
def api(seeded, migrated, tmp_path):  # noqa: F811
    cells(seeded)
    with TestClient(create_app(migrated[0], LocalBlobStore(tmp_path))) as c:
        yield c, seeded


def _pv(conn, code: str, path: str) -> int:
    return conn.execute("SELECT pv.id FROM regulation.provision_version pv JOIN regulation.provision p ON p.id = pv.provision_id"
                        " WHERE p.work_id = %s AND pv.path = %s", (wid(code), path)).fetchone()["id"]


def test_article_with_compare_cells(api):
    c, conn = api
    for path in ("a27", "a27.p1"):           # 조든 그 아래 항이든 같은 조로 본다
        d = c.get("/api/v1/provision/compare", params={"pv": _pv(conn, "KASI", path)}).json()
        assert (d["work_id"], d["institution"], d["article_path"]) == (wid("KASI"), "KASI", "a27")
        assert d["topics"] == ["travel"]
        cell = d["cells"][0]
        assert (cell["topic"], cell["item"], cell["value"], cell["path"]) == ("travel", "evidence_deadline", "7일", "a27.p1")
        assert cell["item_label"] == "출장 증빙 제출 기한" and cell["topic_label"] == "여비·출장"


def test_article_without_cells_and_unknown_pv(api):
    c, conn = api
    d = c.get("/api/v1/provision/compare", params={"pv": _pv(conn, "KASI", "a1")}).json()
    assert d["cells"] == [] and d["topics"] == ["travel"] and d["article_path"] == "a1"
    assert c.get("/api/v1/provision/compare", params={"pv": 999_999_999}).status_code == 404
