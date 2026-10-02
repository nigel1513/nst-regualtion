import json
from datetime import date, datetime

import psycopg
from psycopg.rows import dict_row

from reg.ops.tasks import KST, SUMMARY_DAG, collect_summary, daily_summary

W = "kr/reg/KASI/여비규정"


def _seed(conn):
    inst = conn.execute("INSERT INTO regulation.institution (code, name, kind) VALUES ('KASI', '한국천문연구원', 'GRI')"
                        " RETURNING id").fetchone()["id"]
    sd_new = conn.execute("INSERT INTO regulation.source_document (source, sha256, blob_key, mime, size_bytes, url)"
                          " VALUES ('alio', %s, 'raw/aa/a', 'application/pdf', 1, 'http://x/1') RETURNING id",
                          ("a" * 64,)).fetchone()["id"]
    sd_old = conn.execute("INSERT INTO regulation.source_document (source, sha256, blob_key, mime, size_bytes, url,"
                          " fetched_at) VALUES ('alio', %s, 'raw/bb/b', 'application/pdf', 1, 'http://x/2',"
                          " now() - interval '2 days') RETURNING id", ("b" * 64,)).fetchone()["id"]
    conn.execute("INSERT INTO regulation.work (id, kind, institution_id, title) VALUES (%s, 'INTERNAL_REG', %s, '여비규정')",
                 (W, inst))
    for vid, sd, age in ((f"{W}@2026-10-01", sd_new, "0 days"), (f"{W}@2025-01-01", sd_old, "2 days")):
        conn.execute("INSERT INTO regulation.work_version (id, work_id, source_document_id, title, effective_basis,"
                     " effective_status, parsed, created_at) VALUES (%s, %s, %s, '여비규정', 'supp', 'CONFIRMED', '{}',"
                     " now() - %s::interval)", (vid, W, sd, age))
    conn.execute("INSERT INTO regulation.review_task (kind, target, work_id) VALUES ('LOW_TEXT', 'sd:1', %s)", (W,))
    conn.execute("INSERT INTO ops.change_impact (cause_work_id, cause_version_id, cause_path, cause_change,"
                 " affected_work_id, affected_path, rel_type, impact_kind, severity)"
                 " VALUES ('kr/law/1', 'v1', 'a1', 'MODIFIED', %s, 'a3', 'BASIS', 'BASIS_CHANGED', 'HIGH')", (W,))
    conn.execute("INSERT INTO ops.release (state, os_index, embedding_model, published_at)"
                 " VALUES ('PUBLISHED', 'nais-regulations-r7', 'bge-m3', now())")
    conn.execute("INSERT INTO ops.fetch_run (source, scope, status) VALUES ('alio', 'KASI', 'failed')")
    conn.execute("INSERT INTO ops.outbox (topic, payload, attempts) VALUES ('regulation.source_fetched', '{}', 3),"
                 " ('regulation.source_fetched', '{}', 1)")
    conn.execute("INSERT INTO ops.pipeline_run (dag_id, run_id, task_id, status, stats) VALUES"
                 " ('reg_alio_daily', 'r1', 'collect', 'failed', '{\"source\": \"on_failure_callback\"}'),"
                 " ('reg_alio_daily', 'r1', 'collect', 'failed', '{}'),"          # 재시도 중 실패: 세지 않음
                 " ('reg_publish', 'r0', 'index_build', 'failed', '{\"source\": \"on_failure_callback\"}')")
    conn.execute("UPDATE ops.pipeline_run SET started_at = now() - interval '2 days' WHERE run_id = 'r0'")
    conn.commit()


def test_collect_summary_counts_today_only(conn):
    _seed(conn)
    today = datetime.now(KST).date()
    s = collect_summary(conn, today)
    assert s["day"] == today.isoformat()
    assert s["collected"] == {"documents": {"alio": 1}, "runs": {"alio": {"runs": 1, "failed": 1}}}
    assert s["new_versions"] == 1
    assert s["failures"] == {"tasks": ["reg_alio_daily.collect"], "held_events": 1}
    assert s["review_queue"] == {"new": 1, "open": 1}
    assert s["impacts"] == {"HIGH": 1}
    assert s["abolished_candidates"] == 0
    assert s["release"]["os_index"] == "nais-regulations-r7"
    json.dumps(s)


def test_quiet_day_is_all_zero(conn):
    s = collect_summary(conn, date(2020, 1, 1))
    assert s["collected"] == {"documents": {}, "runs": {}} and s["new_versions"] == 0
    assert s["failures"]["tasks"] == [] and s["impacts"] == {} and s["release"] is None


def test_daily_summary_writes_one_row_per_day(conn, app_dsn):
    _seed(conn)
    first = daily_summary()
    second = daily_summary()
    assert first == second
    with psycopg.connect(app_dsn, row_factory=dict_row) as c:
        rows = c.execute("SELECT run_id, task_id, status, stats FROM ops.pipeline_run WHERE dag_id = %s",
                         (SUMMARY_DAG,)).fetchall()
        runs = c.execute("SELECT count(*) AS n FROM ops.pipeline_run WHERE task_id = 'reg.ops.tasks.daily_summary'"
                         " AND status = 'success'").fetchone()["n"]
    assert len(rows) == 1 and rows[0]["run_id"] == f"summary:{first['day']}"
    assert rows[0]["status"] == "success" and rows[0]["stats"]["new_versions"] == 1
    assert runs == 2   # task_run 실행 기록은 실행마다 남는다


def test_daily_summary_accepts_day_string(conn, app_dsn):
    assert daily_summary("2020-01-01")["day"] == "2020-01-01"
