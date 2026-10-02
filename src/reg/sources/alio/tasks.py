"""Airflow·CLI 진입점 (overview §2.6). 결과는 JSON으로 직렬화할 수 있는 dict."""
from reg.platform.runs import open_conn, task_run
from reg.sources.alio.config import INSTITUTIONS_YAML


def active_institutions() -> list[str]:
    from reg.sources.alio.sync import load_institutions

    with open_conn() as conn:
        return [i["code"] for i in load_institutions(conn, INSTITUTIONS_YAML)]


def collect_institution(code: str) -> dict:
    """기관 하나의 ALIO 목록·상세·파일 수집 (요청 로그는 ops.request_log, 실행 이력은 fetch_run + pipeline_run)."""
    from reg.platform.http import PoliteClient
    from reg.platform.runs import run_logged
    from reg.platform.settings import get_settings
    from reg.platform.storage.blob import blob_store
    from reg.sources.alio.client import AlioClient
    from reg.sources.alio.sync import load_institutions, sync_institution

    def body(conn, log):
        inst = next(i for i in load_institutions(conn, INSTITUTIONS_YAML) if i["code"] == code)
        http = PoliteClient("alio", get_settings().alio_min_interval, log=log)
        return sync_institution(conn, AlioClient(http), blob_store(), inst)

    with task_run(f"alio.collect:{code}") as st:
        run_id, stats = run_logged("alio", code, body)
        st.update(stats, institution=code, fetch_run_id=run_id)
        return dict(st)
