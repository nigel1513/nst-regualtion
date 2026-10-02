import json
from collections.abc import Callable

from reg.platform.http import RequestLog


def start_run(conn, source: str, scope: str | None) -> int:
    row = conn.execute("INSERT INTO regulation.fetch_run (source, scope) VALUES (%s, %s) RETURNING id",
                       (source, scope)).fetchone()
    conn.commit()
    return row["id"]


def finish_run(conn, run_id: int, status: str, stats: dict, error: str | None = None) -> None:
    conn.rollback()  # 실패한 규정의 미커밋 변경은 버린다
    conn.execute("UPDATE regulation.fetch_run SET finished_at = now(), status = %s, stats = %s, error = %s"
                 " WHERE id = %s", (status, json.dumps(stats, ensure_ascii=False), error, run_id))
    conn.commit()


def open_log_conn(dsn: str):
    """request_log 전용 autocommit 연결: 규정 작업이 롤백돼도 요청 기록(특히 중지 원인)은 남는다."""
    import psycopg

    return psycopg.connect(dsn, autocommit=True)


def db_logger(conn, run_id: int) -> Callable[[RequestLog], None]:
    def log(r: RequestLog) -> None:
        conn.execute("INSERT INTO regulation.request_log (run_id, source, url, status, bytes, elapsed_ms,"
                     " waited_ms, error) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                     (run_id, r.source, r.url, r.status, r.bytes, r.elapsed_ms, r.waited_ms, r.error))
    return log


def run_logged(source: str, scope: str | None, body):
    """수집·처리 한 번을 regulation.fetch_run에 기록하며 실행한다. body(conn, log) -> stats."""
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
