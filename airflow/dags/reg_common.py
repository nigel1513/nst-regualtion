"""DAG 공통: 시간대, Asset, 재시도 묶음, 실패 기록 콜백, watcher.

DAG 파일은 여기와 airflow만 최상위에서 import한다. reg는 태스크 함수 안에서만 import한다(overview §2.6).
"""
from __future__ import annotations

import logging
from datetime import timedelta

import pendulum
from airflow.sdk import Asset, task

try:  # Airflow 3.x: 시간표 클래스가 SDK로 옮겨지는 중이다
    from airflow.sdk import AssetOrTimeSchedule, CronTriggerTimetable
except ImportError:  # pragma: no cover
    from airflow.timetables.assets import AssetOrTimeSchedule
    from airflow.timetables.trigger import CronTriggerTimetable

try:
    from airflow.sdk.exceptions import AirflowSkipException
except ImportError:  # pragma: no cover
    from airflow.exceptions import AirflowSkipException

log = logging.getLogger(__name__)

TZ = "Asia/Seoul"
START = pendulum.datetime(2026, 10, 1, tz=TZ)

RAW = Asset("regulation_raw")              # ALIO 원본 수집 완료
LAW_MIRROR = Asset("law_mirror")           # 법령 미러·승격 완료
STRUCTURED = Asset("regulation_structured")  # 파싱·적재 완료
OCR_DONE = Asset("regulation_ocr")         # OCR로 새 텍스트가 생김 (처리 건이 있을 때만)
LAW_PROMOTED = Asset("law_promoted")       # 인용 법령 승격으로 처리할 이벤트가 생김 (승격 건이 있을 때만)


def failure_fields(context) -> dict:
    ti = context["ti"]
    exc = context.get("exception")
    return {"dag_id": ti.dag_id, "run_id": ti.run_id, "task_id": ti.task_id,
            "map_index": getattr(ti, "map_index", -1), "try_number": getattr(ti, "try_number", None),
            "error": f"{type(exc).__name__}: {exc}" if exc is not None else "알 수 없는 실패"}


def record_failure(context) -> None:
    """마지막 재시도까지 실패한 태스크를 ops.pipeline_run에 남긴다. 메일은 보내지 않는다(D-6). 예외를 내지 않는다."""
    try:
        from reg.ops.failures import record_task_failure

        record_task_failure(**failure_fields(context))
    except Exception:
        log.exception("ops.pipeline_run에 실패 기록을 남기지 못함")


DEFAULT_ARGS = {"owner": "nst-regulation", "retries": 1, "retry_delay": timedelta(minutes=5),
                "execution_timeout": timedelta(minutes=30), "on_failure_callback": record_failure}

# spec §2.3
COLLECT = {"retries": 3, "retry_delay": timedelta(minutes=5), "retry_exponential_backoff": True,
           "max_retry_delay": timedelta(minutes=40), "execution_timeout": timedelta(minutes=60)}
PARSE = {"retries": 1, "retry_delay": timedelta(minutes=10), "execution_timeout": timedelta(minutes=120)}
INDEX = {"retries": 6, "retry_delay": timedelta(minutes=30), "execution_timeout": timedelta(minutes=90)}
LIGHT = {"retries": 2, "retry_delay": timedelta(minutes=10), "execution_timeout": timedelta(minutes=30)}
ONCE = {"retries": 1, "retry_delay": timedelta(minutes=5), "execution_timeout": timedelta(minutes=30)}
MARK = {"retries": 0, "execution_timeout": timedelta(minutes=5)}
GATE = {"retries": 0, "execution_timeout": timedelta(minutes=30)}  # 게이트 결과는 재시도해도 같다 (M6-4)


def cron(expr: str) -> CronTriggerTimetable:
    return CronTriggerTimetable(expr, timezone=TZ)


def cron_or_assets(expr: str, assets) -> AssetOrTimeSchedule:
    return AssetOrTimeSchedule(timetable=cron(expr), assets=assets)


def dag_kwargs(doc: str | None) -> dict:
    return {"start_date": START, "catchup": False, "max_active_runs": 1, "default_args": DEFAULT_ARGS,
            "tags": ["nst-regulation"], "doc_md": doc}


def skip(reason: str):
    raise AirflowSkipException(reason)


@task(trigger_rule="one_failed", retries=0, on_failure_callback=None, execution_timeout=timedelta(minutes=5))
def watcher() -> None:
    """상위 태스크가 하나라도 실패하면 실행되어 DAG 실행 전체를 실패로 표시한다(all_done 태스크가 가리지 않게)."""
    raise RuntimeError("상위 태스크 중 실패가 있음 — Airflow UI에서 빨간 태스크를 확인하세요")
