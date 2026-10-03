"""Airflow·CLI 진입점 (overview §2.6). 출처 처리기 등록(reg.wiring.register_sources)은 호출자가 먼저 한다."""
from reg.platform.runs import open_conn, task_run


def process_all() -> dict:
    """대기 중인 수집 이벤트를 모두 처리한다 (추출·파싱·적재·계보·참조·품질·개정 이벤트)."""
    from reg.core.ingest.process import process_once
    from reg.platform.convert import get_converter
    from reg.platform.storage.blob import blob_store

    with open_conn() as conn, task_run("core.process_all", conn) as st:
        total = {"claimed": 0, "ok": 0, "failed": 0, "parked": 0}
        blob, converter = blob_store(), get_converter()
        while (r := process_once(conn, blob, converter=converter))["claimed"]:
            total = {k: total[k] + r[k] for k in total}
            if r["ok"] == 0:
                break
        st.update(total)
        return dict(st)


def reresolve_refs(processed: dict | None = None) -> dict:
    """참조 재해석 (process_all 뒤): 미해석·모호 참조가 있는 work를 다시 해석하고 바뀐 work만 다시 쓴다.

    먼저 처리된 규정이 이번에 적재된 규정을 가리키면 그때는 미해석이었다. processed(process_all 결과)에서
    새로 적재된 것이 없으면(ok=0) 바뀔 것이 없으므로 건너뛴다. 그래프는 이 뒤의 graph.sync가 증분으로 맞춘다."""
    from reg.core.refs import reresolve

    with open_conn() as conn, task_run("core.refs_reresolve", conn) as st:
        if processed is not None and not processed.get("ok"):
            st["skipped"] = "이번 처리에서 적재된 규정 없음"
            return dict(st)
        st.update(reresolve(conn))
        return dict(st)


def quality_summary() -> dict:
    """열린 검수 작업 종류별 수와 오늘 새로 생긴 수."""
    with open_conn() as conn, task_run("core.quality_summary", conn) as st:
        rows = conn.execute("SELECT kind, count(*) AS n, count(*) FILTER (WHERE created_at::date = current_date) AS today"
                            " FROM regulation.review_task WHERE status = 'OPEN' GROUP BY kind").fetchall()
        st.update({"open": {r["kind"]: r["n"] for r in rows}, "new_today": {r["kind"]: r["today"] for r in rows}})
        return dict(st)
