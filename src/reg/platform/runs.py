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
