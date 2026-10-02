"""Airflow·CLI 진입점 (overview §2.6). 스스로 설정을 읽고 연결하며, ops.pipeline_run에 남기고, JSON dict를 돌려준다.

수집(sync_daily·sync_full·fetch_annexes)은 ops.fetch_run과 요청 로그(OC 가림)도 남긴다.
항목 하나라도 실패하면 LawGoError를 던진다. 다시 돌려도 결과가 같다(멱등).
"""
from datetime import date

from reg.platform.runs import db_logger, finish_run, open_conn, open_log_conn, start_run, task_run
from reg.platform.settings import get_settings
from reg.platform.storage.blob import blob_store
from reg.sources.lawgo.client import make_client
from reg.sources.lawgo.config import load_config
from reg.sources.lawgo.errors import LawGoError
from reg.sources.lawgo.link import link_all
from reg.sources.lawgo.promote import promote_all
from reg.sources.lawgo.sync import run_annex, run_daily, run_full


def _collect(task_id: str, scope: str, body) -> dict:
    s = get_settings()
    with open_conn() as conn, open_log_conn(s.database_url) as log_conn, task_run(task_id, conn) as out:
        fetch_id = start_run(conn, "lawgo", scope)
        try:
            client = make_client(s.lawgo_oc, s.lawgo_min_interval, db_logger(log_conn, fetch_id))
            try:
                st = body(conn, client, blob_store(s), load_config())
            finally:
                client.close()
        except BaseException as e:
            finish_run(conn, fetch_id, "failed", {}, f"{type(e).__name__}: {e}"[:2000])
            raise
        finish_run(conn, fetch_id, "failed" if st.get("errors") else "succeeded", st)
        out.update(st)
        if st.get("errors"):
            raise LawGoError(f"{scope}: {len(st['errors'])}건 실패 — " + " | ".join(st["errors"][:3]))
        return dict(st)


def sync_daily(day: str | None = None) -> dict:
    d = date.fromisoformat(day) if day else None
    return _collect("lawgo.sync_daily", "daily", lambda c, cl, b, cfg: run_daily(c, cl, b, cfg, d))


def sync_full() -> dict:
    return _collect("lawgo.sync_full", "full", lambda c, cl, b, cfg: run_full(c, cl, b, cfg))


def fetch_annexes(limit: int = 2000) -> dict:
    """CLI 전용(DAG 계약 밖): 밀린 별표 본문을 limit건 받는다."""
    return _collect("lawgo.fetch_annexes", "annex", lambda c, cl, b, cfg: run_annex(c, cl, b, cfg, limit))


def link() -> dict:
    with open_conn() as conn, task_run("lawgo.link", conn) as out:
        st = link_all(conn)
        conn.commit()
        out.update(st)
        return dict(st)


def promote() -> dict:
    with open_conn() as conn, task_run("lawgo.promote", conn) as out:
        st = promote_all(conn, load_config())
        out.update(st)
        return dict(st)
