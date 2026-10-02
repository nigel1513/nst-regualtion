import psycopg
from psycopg.rows import dict_row

from reg.ops.failures import FAILURE_SOURCE, record_task_failure


def test_record_task_failure(app_dsn):
    rid = record_task_failure(dag_id="reg_publish", run_id="manual__1", task_id="index_build",
                              error="RuntimeError: " + "x" * 5000, map_index=-1, try_number=7)
    with psycopg.connect(app_dsn, row_factory=dict_row) as c:
        r = c.execute("SELECT * FROM ops.pipeline_run WHERE id = %s", (rid,)).fetchone()
    assert (r["dag_id"], r["task_id"], r["status"]) == ("reg_publish", "index_build", "failed")
    assert r["stats"] == {"source": FAILURE_SOURCE, "map_index": -1, "try_number": 7}
    assert len(r["error"]) == 4000 and r["finished_at"] is not None


def test_explicit_dsn_wins(migrated, monkeypatch):
    monkeypatch.setenv("REG_DATABASE_URL", "postgresql://nobody:x@127.0.0.1:1/none")
    rid = record_task_failure(dag_id="d", run_id="r", task_id="t", error="E", dsn=migrated[0])
    assert isinstance(rid, int)
