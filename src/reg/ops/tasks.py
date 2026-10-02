"""운영 진입점: 하루 요약, 정리 작업 (overview §2.6, spec §8·§9). Airflow와 CLI(reg ops)가 같이 부른다."""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from reg.ops.failures import FAILURE_SOURCE
from reg.platform.db.conn import connect
from reg.platform.runs import task_run
from reg.platform.settings import get_settings

KST = ZoneInfo("Asia/Seoul")
SUMMARY_DAG = "reg_summary"
HOLD_ATTEMPTS = 3  # core 처리기의 MAX_ATTEMPTS: 이만큼 실패한 이벤트는 보류(검수 화면)


def _window(day: date) -> dict:
    lo = datetime.combine(day, time.min, tzinfo=KST)
    return {"lo": lo, "hi": lo + timedelta(days=1)}


def collect_summary(conn, day: date) -> dict:
    w = _window(day)
    docs = {r["source"]: r["n"] for r in conn.execute(
        "SELECT source, count(*) AS n FROM regulation.source_document"
        " WHERE fetched_at >= %(lo)s AND fetched_at < %(hi)s GROUP BY source ORDER BY source", w)}
    runs = {r["source"]: {"runs": r["runs"], "failed": r["failed"]} for r in conn.execute(
        "SELECT source, count(*) AS runs, count(*) FILTER (WHERE status = 'failed') AS failed FROM ops.fetch_run"
        " WHERE started_at >= %(lo)s AND started_at < %(hi)s GROUP BY source ORDER BY source", w)}
    new_versions = conn.execute(
        "SELECT count(*) AS n FROM regulation.work_version WHERE created_at >= %(lo)s AND created_at < %(hi)s",
        w).fetchone()["n"]
    failed = [r["t"] for r in conn.execute(
        "SELECT DISTINCT dag_id || '.' || task_id AS t FROM ops.pipeline_run"
        " WHERE status = 'failed' AND stats->>'source' = %(src)s AND started_at >= %(lo)s AND started_at < %(hi)s"
        " ORDER BY 1", {**w, "src": FAILURE_SOURCE})]
    held = conn.execute("SELECT count(*) AS n FROM ops.outbox WHERE processed_at IS NULL AND attempts >= %s",
                        (HOLD_ATTEMPTS,)).fetchone()["n"]
    review = conn.execute(
        "SELECT count(*) FILTER (WHERE created_at >= %(lo)s AND created_at < %(hi)s) AS new,"
        " count(*) FILTER (WHERE status = 'OPEN') AS open FROM regulation.review_task", w).fetchone()
    impacts = {r["severity"]: r["n"] for r in conn.execute(
        "SELECT severity, count(*) AS n FROM ops.change_impact WHERE created_at >= %(lo)s AND created_at < %(hi)s"
        " GROUP BY severity ORDER BY severity", w)}
    abolished = conn.execute(
        "SELECT count(*) AS n FROM regulation.work WHERE status = 'ABOLISHED_CANDIDATE'").fetchone()["n"]
    rel = conn.execute(
        "SELECT id, os_index, published_at FROM ops.release WHERE state = 'PUBLISHED'"
        " AND published_at >= %(lo)s AND published_at < %(hi)s ORDER BY published_at DESC LIMIT 1", w).fetchone()
    return {
        "day": day.isoformat(),
        "collected": {"documents": docs, "runs": runs},
        "new_versions": new_versions,
        "failures": {"tasks": failed, "held_events": held},
        "review_queue": {"new": review["new"], "open": review["open"]},
        "impacts": impacts,
        "abolished_candidates": abolished,
        "release": None if rel is None else {
            "id": rel["id"], "os_index": rel["os_index"], "published_at": rel["published_at"].isoformat()},
    }


def save_summary(conn, summary: dict) -> None:
    run_id = f"summary:{summary['day']}"
    conn.execute("DELETE FROM ops.pipeline_run WHERE dag_id = %s AND run_id = %s", (SUMMARY_DAG, run_id))
    conn.execute("INSERT INTO ops.pipeline_run (dag_id, run_id, task_id, finished_at, status, stats)"
                 " VALUES (%s, %s, 'daily_summary', now(), 'success', %s)",
                 (SUMMARY_DAG, run_id, json.dumps(summary, ensure_ascii=False)))


def daily_summary(day: str | None = None) -> dict:
    d = date.fromisoformat(day) if day else datetime.now(KST).date()
    with task_run("reg.ops.tasks.daily_summary") as stats:
        conn = connect(get_settings().database_url)
        try:
            summary = collect_summary(conn, d)
            save_summary(conn, summary)
            conn.commit()
        finally:
            conn.close()
        stats.update(summary)
    return summary
