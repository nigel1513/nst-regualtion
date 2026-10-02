from reg.platform.http import RequestLog
from reg.platform.runs import db_logger, finish_run, start_run


def test_run_lifecycle_and_request_log(conn):
    run_id = start_run(conn, "alio", "KASI")
    db_logger(conn, run_id)(RequestLog("alio", "https://x", 200, 10, 5, 0))
    conn.commit()
    finish_run(conn, run_id, "succeeded", {"n": 1})
    r = conn.execute("SELECT status, stats, finished_at FROM ops.fetch_run WHERE id=%s", (run_id,)).fetchone()
    assert r["status"] == "succeeded" and r["stats"] == {"n": 1} and r["finished_at"] is not None
    assert conn.execute("SELECT count(*) AS n FROM ops.request_log WHERE run_id=%s", (run_id,)).fetchone()["n"] == 1


def test_finish_failed_discards_uncommitted_work(conn):
    run_id = start_run(conn, "alio", None)
    conn.execute("INSERT INTO ops.outbox (topic, payload) VALUES ('x', '{}')")
    finish_run(conn, run_id, "failed", {}, "boom")
    assert conn.execute("SELECT count(*) AS n FROM ops.outbox").fetchone()["n"] == 0


def test_request_log_survives_failed_run(conn, migrated):
    from reg.platform.runs import open_log_conn

    run_id = start_run(conn, "alio", None)
    log_conn = open_log_conn(migrated[0])
    db_logger(log_conn, run_id)(RequestLog("alio", "https://x", 403, 0, 5, 0))
    finish_run(conn, run_id, "failed", {}, "403")
    log_conn.close()
    assert conn.execute("SELECT count(*) AS n FROM ops.request_log WHERE run_id=%s", (run_id,)).fetchone()["n"] == 1
