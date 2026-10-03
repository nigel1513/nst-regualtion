import pytest
from fastapi.testclient import TestClient

from reg.api.app import create_app
from reg.graph.sync import rebuild
from reg.platform.storage.blob import LocalBlobStore
from tests.test_graph import build, pv


class DownDriver:
    def session(self):
        from neo4j.exceptions import ServiceUnavailable

        raise ServiceUnavailable("neo4j down")


@pytest.fixture
def api(conn, migrated, tmp_path, neo4j_driver):
    build(conn, tmp_path)
    rebuild(conn, neo4j_driver)
    app = create_app(migrated[0], LocalBlobStore(tmp_path))
    app.state.graph_driver = neo4j_driver
    with TestClient(app) as c:
        yield c, conn, app


def test_neighborhood_lineage_expand(api):
    c, conn, _ = api
    a3 = pv(conn, "kr/reg/KASI/여비", "a3")
    n = c.get("/api/v1/graph/neighborhood", params={"pv": a3, "depth": 2}).json()
    assert n["center"] == f"pv:{a3}" and any(e["type"] == "BASIS" for e in n["edges"])
    lin = c.get("/api/v1/graph/lineage", params={"pv": pv(conn, "kr/law/L1", "a5")}).json()
    assert [e["change"] for e in lin["entries"]] == [None, "MODIFIED"]
    ex = c.get("/api/v1/graph/expand", params={"pv": [pv(conn, "kr/reg/KASI/출장", "a3.p1")], "as_of": "2026-10-03"}).json()
    assert {"용어 정의: 여비", "상위 조문", "예외 조항"} <= {e["reason"] for e in ex["items"]}
    assert ex["as_of"] == "2026-10-03"


def test_errors(api):
    c, _, app = api
    assert c.get("/api/v1/graph/neighborhood", params={"pv": 999999999}).status_code == 404
    assert c.get("/api/v1/graph/lineage", params={"pv": 999999999}).status_code == 404
    assert c.get("/api/v1/graph/neighborhood", params={"pv": 1, "depth": 3}).status_code == 422
    assert c.get("/api/v1/graph/expand").status_code == 422
    app.state.graph_driver = DownDriver()
    assert c.get("/api/v1/graph/lineage", params={"pv": 1}).status_code == 503
