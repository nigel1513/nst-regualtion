import json
import os
from collections.abc import Callable
from contextlib import contextmanager

from reg.platform.http import RequestLog


def start_run(conn, source: str, scope: str | None) -> int:
    row = conn.execute("INSERT INTO ops.fetch_run (source, scope) VALUES (%s, %s) RETURNING id",
                       (source, scope)).fetchone()
    conn.commit()
    return row["id"]


def finish_run(conn, run_id: int, status: str, stats: dict, error: str | None = None) -> None:
    conn.rollback()  # 실패한 규정의 미커밋 변경은 버린다
    conn.execute("UPDATE ops.fetch_run SET finished_at = now(), status = %s, stats = %s, error = %s"
                 " WHERE id = %s", (status, json.dumps(stats, ensure_ascii=False), error, run_id))
    conn.commit()


def open_log_conn(dsn: str):
    """request_log 전용 autocommit 연결: 규정 작업이 롤백돼도 요청 기록(특히 중지 원인)은 남는다."""
    import psycopg

    return psycopg.connect(dsn, autocommit=True)


def db_logger(conn, run_id: int) -> Callable[[RequestLog], None]:
    def log(r: RequestLog) -> None:
        conn.execute("INSERT INTO ops.request_log (run_id, source, url, status, bytes, elapsed_ms,"
                     " waited_ms, error) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                     (run_id, r.source, r.url, r.status, r.bytes, r.elapsed_ms, r.waited_ms, r.error))
    return log


def run_logged(source: str, scope: str | None, body):
    """수집·처리 한 번을 ops.fetch_run에 기록하며 실행한다. body(conn, log) -> stats."""
    from reg.platform.db.conn import connect
    from reg.platform.settings import get_settings

    dsn = get_settings().database_url
    conn, log_conn = connect(dsn), open_log_conn(dsn)
    run_id = start_run(conn, source, scope)
    try:
        stats = body(conn, db_logger(log_conn, run_id))
    except BaseException as e:  # Ctrl-C·SIGTERM 포함: 실행 상태를 남기고 그대로 전파
        finish_run(conn, run_id, "failed", {}, f"{type(e).__name__}: {e}")
        raise
    else:
        finish_run(conn, run_id, "succeeded", stats)
        return run_id, stats
    finally:
        log_conn.close()
        conn.close()


def open_conn():
    """설정의 앱 DSN으로 새 연결 (배치 진입점용)."""
    from reg.platform.db.conn import connect
    from reg.platform.settings import get_settings

    return connect(get_settings().database_url)


@contextmanager
def task_run(task_id: str, conn=None):
    """배치 태스크 한 번의 실행을 ops.pipeline_run에 남긴다 (Airflow·CLI 공통). conn이 없으면 따로 연다.

    블록 안에서 채운 dict가 stats로 저장되고, 예외는 failed·error로 기록한 뒤 그대로 다시 던진다."""
    own = conn is None
    rec = open_conn() if own else conn
    try:
        rid = rec.execute("INSERT INTO ops.pipeline_run (dag_id, run_id, task_id) VALUES (%s, %s, %s) RETURNING id",
                          (os.environ.get("AIRFLOW_CTX_DAG_ID"), os.environ.get("AIRFLOW_CTX_DAG_RUN_ID"),
                           task_id)).fetchone()["id"]
        rec.commit()
        stats: dict = {}
        try:
            yield stats
        except BaseException as e:
            rec.rollback()
            rec.execute("UPDATE ops.pipeline_run SET status = 'failed', finished_at = now(), stats = %s, error = %s"
                        " WHERE id = %s", (json.dumps(stats, default=str), f"{type(e).__name__}: {e}"[:2000], rid))
            rec.commit()
            raise
        rec.execute("UPDATE ops.pipeline_run SET status = 'success', finished_at = now(), stats = %s WHERE id = %s",
                    (json.dumps(stats, default=str), rid))
        rec.commit()
    finally:
        if own:
            rec.close()
