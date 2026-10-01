import json
from datetime import date

from reg.alerts.scan import scan_once
from reg.graph.sync import sync_graph
from reg.process import emit_version_events, process_once
from reg.storage.blob import LocalBlobStore
from reg.structure.model import Prov
from tests.test_impact import _ver, law_v1, setup
from tests.test_process import FX, seed_alio

TOPIC = "regulation.version_loaded"


def events(conn):
    return [r["payload"] for r in conn.execute("SELECT payload FROM regulation.outbox WHERE topic = %s ORDER BY id",
                                               (TOPIC,)).fetchall()]


def test_first_load_emits_no_version_loaded(conn, tmp_path):
    blob = LocalBlobStore(tmp_path)
    seed_alio(conn, blob, (FX / "samples" / "kasi-yeobi-339.pdf").read_bytes())
    process_once(conn, blob, today=date(2026, 10, 2))
    assert events(conn) == []


def test_only_versions_newer_than_existing_ones_emit(conn, tmp_path):
    from reg.load.loader import upsert_work

    blob = LocalBlobStore(tmp_path)
    upsert_work(conn, "kr/law/L1", "법률", "가상 연구법", None, {})
    _ver(conn, blob, "kr/law/L1", "가상 연구법", law_v1(), date(2020, 1, 1), b"L1")
    assert emit_version_events(conn, "kr/law/L1") == 0  # 같은 트랜잭션에서 처음 적재
    conn.commit()
    old = _ver(conn, blob, "kr/law/L1", "가상 연구법", law_v1(), date(2018, 1, 1), b"L0")  # 과거 버전이 뒤늦게 수집
    new = _ver(conn, blob, "kr/law/L1", "가상 연구법", law_v1(), date(2026, 1, 1), b"L2")
    assert emit_version_events(conn, "kr/law/L1") == 1
    assert events(conn) == [{"work_id": "kr/law/L1", "version_id": new}] and old != new


class DownDriver:
    def session(self):
        raise RuntimeError("neo4j down")


def test_scan_retries_when_graph_is_down_then_processes(conn, tmp_path, neo4j_driver):
    vid = setup(conn, tmp_path, [Prov("a5", "article", "제5조", "정산", "정산은 10일 이내에 한다."),
                                 Prov("a6", "article", "제6조", "기록", "기록한다.")])
    conn.execute("INSERT INTO regulation.outbox (topic, payload) VALUES (%s, %s)",
                 (TOPIC, json.dumps({"work_id": "kr/law/L1", "version_id": vid})))
    conn.commit()
    assert scan_once(conn, DownDriver()) == {"claimed": 1, "ok": 0, "failed": 1, "impacts": 0}
    ev = conn.execute("SELECT processed_at, attempts FROM regulation.outbox WHERE topic = %s", (TOPIC,)).fetchone()
    assert ev["processed_at"] is None and ev["attempts"] == 1
    sync_graph(conn, neo4j_driver)
    st = scan_once(conn, neo4j_driver)
    assert st["ok"] == 1 and st["impacts"] == 1
    assert scan_once(conn, neo4j_driver)["claimed"] == 0
