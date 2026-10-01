from fastapi.testclient import TestClient

from reg.api.app import create_app
from reg.storage.blob import LocalBlobStore
from tests.test_notify import impact, owner


def test_alerts_list_detail_and_status(conn, migrated, tmp_path):
    iid = impact(conn)
    low = impact(conn, path="a8", sev="LOW")
    owner(conn, "owner@x")
    conn.commit()
    with TestClient(create_app(migrated[0], LocalBlobStore(tmp_path))) as c:
        rows = c.get("/api/v1/alerts", params={"status": "open"}).json()
        assert [r["id"] for r in rows] == [iid, low]  # 심각도 순
        assert rows[0]["severity"] == "HIGH" and rows[0]["affected_title"] is None  # 규범문서가 없는 가상 데이터
        d = c.get(f"/api/v1/alerts/{iid}").json()
        assert d["affected_path"] == "a3" and d["recipients"] == ["owner@x"]
        assert {"cause_old", "cause_new", "affected_text"} <= set(d)
        assert c.get("/api/v1/alerts/999999").status_code == 404
        assert c.post(f"/api/v1/alerts/{iid}/status", json={"status": "NO_ACTION"}).status_code == 422
        assert c.post(f"/api/v1/alerts/{iid}/status", json={"status": "NO_ACTION", "note": "영향 없음 확인"}).json()["ok"]
        assert [r["id"] for r in c.get("/api/v1/alerts", params={"status": "open"}).json()] == [low]
        done = c.get("/api/v1/alerts", params={"status": "done"}).json()
        assert done[0]["id"] == iid and done[0]["resolution_note"] == "영향 없음 확인"
        assert c.get("/api/v1/alerts", params={"severity": "LOW"}).json()[0]["id"] == low


def test_detail_shows_sub_changes_under_the_referenced_unit(conn, tmp_path, neo4j_driver):
    from reg.alerts.impact import analyze_version
    from reg.alerts.inbox import alert_detail
    from reg.graph.sync import sync_graph
    from tests.test_impact import Prov, setup

    def law(t1):
        return [Prov("a5", "article", "제5조", "정산", ""), Prov("a5.p1", "paragraph", "①", None, t1, "a5"),
                Prov("a6", "article", "제6조", "기록", "기록한다.")]
    vid = setup(conn, tmp_path, law("7일 이내 정산."), v1=law("5일 이내 정산."))
    sync_graph(conn, neo4j_driver)
    row = next(r for r in analyze_version(conn, neo4j_driver, "kr/law/L1", vid) if r["affected_path"] == "a3")
    d = alert_detail(conn, row["id"])
    assert row["cause_path"] == "a5" and "5일 이내" in d["cause_old"] and "7일 이내" in d["cause_new"]
