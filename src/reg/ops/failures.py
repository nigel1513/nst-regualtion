"""Airflow on_failure_callback이 부르는 실패 기록. 메일은 보내지 않는다(D-6). airflow를 import하지 않는다."""
import json

import psycopg

from reg.platform.settings import get_settings

FAILURE_SOURCE = "on_failure_callback"


def record_task_failure(*, dag_id: str, run_id: str, task_id: str, error: str, map_index: int = -1,
                        try_number: int | None = None, dsn: str | None = None) -> int:
    dsn = dsn or get_settings().database_url
    stats = {"source": FAILURE_SOURCE, "map_index": map_index, "try_number": try_number}
    with psycopg.connect(dsn, autocommit=True, connect_timeout=10) as c:
        return c.execute(
            "INSERT INTO ops.pipeline_run (dag_id, run_id, task_id, finished_at, status, stats, error)"
            " VALUES (%s, %s, %s, now(), 'failed', %s, %s) RETURNING id",
            (dag_id, run_id, task_id, json.dumps(stats), error[:4000])).fetchone()[0]
