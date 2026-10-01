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
