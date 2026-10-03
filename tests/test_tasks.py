import pytest


def test_task_run_records_success_and_failure(conn, monkeypatch):
    from reg.platform.runs import task_run

    monkeypatch.setenv("AIRFLOW_CTX_DAG_ID", "reg_alio_daily")
    with task_run("probe", conn) as st:
        st["n"] = 3
    with pytest.raises(ValueError), task_run("boom", conn):
        raise ValueError("x")
    rows = {r["task_id"]: r for r in conn.execute("SELECT * FROM ops.pipeline_run").fetchall()}
    assert rows["probe"]["status"] == "success" and rows["probe"]["stats"] == {"n": 3}
    assert rows["probe"]["dag_id"] == "reg_alio_daily"
    assert rows["boom"]["status"] == "failed" and "ValueError" in rows["boom"]["error"]


def test_parser_version_recorded(loaded):
    from reg.core.parse import PARSER_VERSION

    v = loaded.execute("SELECT parser_version FROM regulation.work_version LIMIT 1").fetchone()
    assert v["parser_version"] == PARSER_VERSION


def test_tasks_entrypoints_exist():
    from reg.alerts import tasks as at
    from reg.core.ingest import tasks as ct
    from reg.graph import tasks as gt
    from reg.index import tasks as it
    from reg.sources.alio import tasks as alt

    for f in (alt.active_institutions, alt.collect_institution, ct.process_all, ct.reresolve_refs, ct.quality_summary, gt.sync,
              at.scan, at.notify, it.build):
        assert callable(f)


def test_task_run_opens_its_own_connection(migrated, monkeypatch):
    from reg.platform.db.conn import connect
    from reg.platform.runs import task_run
    from reg.platform.settings import get_settings

    monkeypatch.setenv("REG_DATABASE_URL", migrated[0])
    get_settings.cache_clear()
    try:
        with task_run("own") as st:
            st["ok"] = True
    finally:
        get_settings.cache_clear()
    with connect(migrated[0]) as c:
        r = c.execute("SELECT status, stats FROM ops.pipeline_run WHERE task_id = 'own'").fetchone()
        c.execute("DELETE FROM ops.pipeline_run WHERE task_id = 'own'")
        c.commit()
    assert r["status"] == "success" and r["stats"] == {"ok": True}
