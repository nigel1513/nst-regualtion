"""Airflow·CLI 진입점 (overview §2.6). 결과는 JSON으로 직렬화할 수 있는 dict."""
from reg.platform.runs import open_conn, task_run


def run_pending(limit: int = 50, tried: list[int] | None = None) -> dict:
    """GPU PC가 꺼져 있으면 실패하지 않고 {"unavailable": true}를 돌려준다(M6-3 DAG가 나중에 다시 돈다).

    tried는 CLI --all 반복이 이어 쓰는 시도한 이벤트 id 목록이다(Airflow는 넘기지 않는다)."""
    from reg.ocr.service import run_pending as run
    from reg.platform import mineru, ocr
    from reg.platform.settings import get_settings
    from reg.platform.storage import blob as storage

    s = get_settings()
    engine = ocr.MineruOcr(mineru.MineruClient.from_settings(s))  # REG_MINERU_URL이 비면 ValueError
    with open_conn() as conn, task_run("ocr.run_pending", conn) as st:
        st.update(run(conn, storage.blob_store(s), engine, limit=limit, tried=tried))
        return dict(st)
