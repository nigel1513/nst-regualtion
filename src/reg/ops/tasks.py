"""운영 진입점: 하루 요약, 정리 작업 (overview §2.6, spec §8·§9). Airflow와 CLI(reg ops)가 같이 부른다."""
from __future__ import annotations

import importlib
import json
import time as _time
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from reg.ops.failures import FAILURE_SOURCE
from reg.platform.db.conn import connect
from reg.platform.runs import task_run
from reg.platform.settings import get_settings

KST = ZoneInfo("Asia/Seoul")
SUMMARY_DAG = "reg_summary"
HOLD_ATTEMPTS = 3  # core 처리기의 MAX_ATTEMPTS: 이만큼 실패한 이벤트는 보류(검수 화면)
REQUEST_LOG_DAYS = 90   # spec §8
QA_LOG_DAYS = 365       # spec §8 (운영 정책 확인 전 기본값)
AIRFLOW_LOG_DAYS = 30   # spec §8


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


def prune_log_files(root: Path, days: int = AIRFLOW_LOG_DAYS, now: float | None = None) -> int:
    """mtime이 days일 넘은 파일만 지운다. 폴더는 남긴다(실행 중인 태스크가 막 만든 빈 폴더를 지우지 않으려고)."""
    if not root.is_dir():
        return 0
    cutoff = (now if now is not None else _time.time()) - days * 86400
    n = 0
    for p in root.rglob("*"):
        if p.is_file() and p.stat().st_mtime < cutoff:
            p.unlink()
            n += 1
    return n


def _prune_indexes() -> dict:
    """옛 release 색인 삭제는 M6-4의 reg.index.tasks.prune이 맡는다. 아직 없으면 건너뛴다."""
    try:
        mod = importlib.import_module("reg.index.tasks")
    except ModuleNotFoundError as e:
        if (e.name or "").startswith("reg.index"):
            return {"skipped": "reg.index.tasks 없음"}
        raise
    prune = getattr(mod, "prune", None)
    if prune is None:
        return {"skipped": "reg.index.tasks.prune 없음 (M6-4 병합 전)"}
    return prune()


def maintenance() -> dict:
    s = get_settings()
    with task_run("reg.ops.tasks.maintenance") as stats:
        conn = connect(s.database_url)
        try:
            rl = conn.execute("DELETE FROM ops.request_log WHERE at < now() - make_interval(days => %s)",
                              (REQUEST_LOG_DAYS,)).rowcount
            qa = conn.execute("DELETE FROM ops.qa_log WHERE created_at < now() - make_interval(days => %s)",
                              (QA_LOG_DAYS,)).rowcount
            conn.commit()
        finally:
            conn.close()
        stats.update(request_log_deleted=rl, qa_log_deleted=qa)
        stats["airflow_logs_deleted"] = prune_log_files(Path(s.airflow_log_dir)) if s.airflow_log_dir else 0
        stats["index_prune"] = _prune_indexes()
    return dict(stats)
