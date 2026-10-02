# src/reg/core/annex_tasks.py
"""별표 이미지·표 배치 진입점 (Airflow·CLI 공통, overview §2.6 형식). DAG 연결은 통합 단계에서 한다."""
from reg.platform.runs import open_conn, task_run


def current_versions(conn, limit: int) -> list[str]:
    """별표가 있고 보기용 PDF가 있는 현행 판본 (원문 위치를 찾은 별표가 하나 이상)."""
    return [r["id"] for r in conn.execute(
        "SELECT DISTINCT v.id FROM regulation.work_version v"
        " JOIN regulation.source_document sd ON sd.id = v.source_document_id"
        " JOIN regulation.version_provision vp ON vp.work_version_id = v.id"
        " JOIN regulation.provision_version pv ON pv.id = vp.provision_version_id"
        " WHERE v.version_state = 'CURRENT' AND pv.unit = 'annex' AND sd.view_blob_key IS NOT NULL"
        " AND coalesce(vp.anchor, pv.source_anchor) IS NOT NULL ORDER BY v.id LIMIT %s", (limit,)).fetchall()]


def render_current(limit: int = 500) -> dict:
    """현행 판본의 별표 이미지를 미리 그린다 (이미 같은 위치로 그린 것은 건너뛴다)."""
    from reg.core.annex import ensure_rendered
    from reg.platform.storage.blob import blob_store

    with open_conn() as conn, task_run("core.annex_render", conn) as st:
        blob = blob_store()
        st.update({"versions": 0, "annexes": 0, "failed": 0, "errors": []})
        for vid in current_versions(conn, limit):
            try:
                st["annexes"] += len(ensure_rendered(conn, blob, vid)["items"])
                st["versions"] += 1
            except Exception as e:  # 판본 하나의 실패가 배치를 멈추지 않게
                st["failed"] += 1
                st["errors"] = (st["errors"] + [f"{vid}: {type(e).__name__}: {e}"[:200]])[:20]
        return dict(st)


def convert_tables(limit: int = 50) -> dict:
    """현행 판본 별표의 표를 MinerU로 HTML로 바꾼다. 주소가 없으면 건너뛰고, 꺼져 있으면 그 자리에서 멈춘다."""
    from reg.core.annex_mineru import mineru_source
    from reg.core.annex_tables import convert_version
    from reg.platform.storage.blob import blob_store

    with open_conn() as conn, task_run("core.annex_tables", conn) as st:
        source = mineru_source()
        if source is None:
            st["skipped"] = "REG_MINERU_URL 없음"
            return dict(st)
        blob = blob_store()
        st.update({"versions": 0, "ok": 0, "no_table": 0, "failed": 0, "unavailable": 0})
        for vid in current_versions(conn, 10_000):
            if st["versions"] >= limit:
                break
            r = convert_version(conn, blob, vid, source)
            if r["annexes"] == 0:
                continue  # 이미 끝난 판본은 상한에 세지 않는다
            st["versions"] += 1
            for k in ("ok", "no_table", "failed", "unavailable"):
                st[k] += r[k]
            if r["unavailable"]:
                break  # GPU PC가 꺼져 있다: 다음 실행에서 다시
        return dict(st)
