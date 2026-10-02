"""M6-0의 task_run(task_id, conn=None)을 M6-3 쪽 쓰임새(자체 연결, Airflow 문맥)로 확인한다."""
import psycopg
import pytest
from psycopg.rows import dict_row

from reg.platform.runs import task_run


def _rows(dsn):
    with psycopg.connect(dsn, row_factory=dict_row) as c:
        return c.execute("SELECT * FROM ops.pipeline_run ORDER BY id").fetchall()


def test_success_records_stats(app_dsn):
    with task_run("reg.x.tasks.do") as stats:
        stats["n"] = 3
    [r] = _rows(app_dsn)
    assert (r["task_id"], r["status"]) == ("reg.x.tasks.do", "success")
    assert r["stats"] == {"n": 3} and r["finished_at"] is not None and r["error"] is None


def test_failure_is_recorded_and_reraised(app_dsn):
    with pytest.raises(ValueError, match="boom"), task_run("reg.x.tasks.do") as stats:
        stats["partial"] = 1
        raise ValueError("boom")
    [r] = _rows(app_dsn)
    assert r["status"] == "failed" and r["error"] == "ValueError: boom" and r["stats"] == {"partial": 1}


def test_airflow_context_env_is_used(app_dsn, monkeypatch):
    monkeypatch.setenv("AIRFLOW_CTX_DAG_ID", "reg_alio_daily")
    monkeypatch.setenv("AIRFLOW_CTX_DAG_RUN_ID", "scheduled__2026-10-02T17:00:00+00:00")
    with task_run("collect"):
        pass
    [r] = _rows(app_dsn)
    assert (r["dag_id"], r["run_id"], r["task_id"]) == (
        "reg_alio_daily", "scheduled__2026-10-02T17:00:00+00:00", "collect")
