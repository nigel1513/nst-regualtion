"""Airflow·CLI 진입점 (overview §2.6). 결과는 JSON으로 직렬화할 수 있는 dict."""
from reg.platform.runs import open_conn, task_run
from reg.sources.alio.config import INSTITUTIONS_YAML
from reg.sources.alio.sync import sync_institution


def canary_check() -> dict:
    return {"ok": True, "skipped": "canary 미구현 (Task 5)"}


def active_institutions() -> list[str]:
    from reg.sources.alio.sync import load_institutions

    with open_conn() as conn:
        return [i["code"] for i in load_institutions(conn, INSTITUTIONS_YAML)]


def collect_institution(code: str, *, include_inactive: bool = False) -> dict:
    """기관 하나의 ALIO 목록·상세·파일 수집 (요청 로그는 ops.request_log, 실행 이력은 fetch_run + pipeline_run).

    일 배치는 활성 기관만, backfill은 include_inactive=True로 비활성 기관도 받는다.
    반환: {"institution": code, "fetch_run_id": …, **sync_institution 결과(complete·started_at 포함)}"""
    from reg.platform.http import PoliteClient
    from reg.platform.runs import run_logged
    from reg.platform.settings import get_settings
    from reg.platform.storage.blob import blob_store
    from reg.sources.alio.client import AlioClient
    from reg.sources.alio.sync import get_institution, load_institutions

    with task_run(f"alio.collect:{code}") as st:
        with open_conn() as conn:
            load_institutions(conn, INSTITUTIONS_YAML)
            inst = get_institution(conn, code)
        if inst is None or not inst["alio_apba_id"]:
            raise ValueError(f"ALIO 기관이 아님: {code} (config/sources/alio.yaml의 code·alio_apba_id 확인)")
        if not inst["active"] and not include_inactive:
            raise ValueError(f"비활성 기관: {code} — 처음 수집은 `reg alio backfill --institution {code}`")

        def body(conn, log):
            http = PoliteClient("alio", get_settings().alio_min_interval, log=log)
            return sync_institution(conn, AlioClient(http), blob_store(), inst)

        run_id, stats = run_logged("alio", code, body)
        st.update(institution=code, fetch_run_id=run_id, **stats)
        return dict(st)


def reconcile(results: list[dict]) -> dict:
    """완결된 기관 수집만 대조해 사라짐·폐지 후보를 갱신하고 work.status를 맞춘다. results=[]이면 투영만.

    Airflow에서는 trigger_rule="all_done"으로 둔다: 실패한 기관은 결과에 없거나 None이고 건너뛴다."""
    from reg.sources.alio.reconcile import run_reconcile

    with task_run("alio.reconcile") as st:
        with open_conn() as conn:
            out = run_reconcile(conn, list(results or []))
        st.update(out)
        return out


def backfill(code: str) -> dict:
    """신규 기관 전체 수집(활성 여부 무관) → 대조. 파싱은 `reg process --all`로 따로."""
    canary_check()
    result = collect_institution(code, include_inactive=True)
    return {"collect": result, "reconcile": reconcile([result])}
