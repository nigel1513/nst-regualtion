"""법령 전체 대조 (매주 일요일 00:00 KST + 최초 적재는 수동 실행, spec §2.2)

현행 법령 전체 목록과 미러를 대조해 누락·불일치·폐지를 보정한다. 본문은 필요한 법령만 받는다
(`reg law targets`: 설정 시드 + 내부규정 인용 + 시행령·시행규칙). 최초 적재는 수십 분~1시간(요청 간격 1초).
끝나면 Asset `law_mirror` → reg_process → reg_law_link(link → promote).
"""
from datetime import timedelta

from airflow.sdk import dag, task
from reg_common import LAW_MIRROR, cron, dag_kwargs

FULL = {"retries": 2, "retry_delay": timedelta(minutes=30), "execution_timeout": timedelta(hours=12)}


@dag(schedule=cron("0 0 * * 0"), **dag_kwargs(__doc__))
def reg_law_full():
    @task(pool="lawgo_pool", outlets=[LAW_MIRROR], **FULL)
    def sync_full() -> dict:
        from reg.sources.lawgo.tasks import sync_full as run

        return run()

    sync_full()


reg_law_full()
