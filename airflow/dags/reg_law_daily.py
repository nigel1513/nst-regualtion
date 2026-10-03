"""법령 일 배치 (매일 01:00 KST, spec §3A.4)

law.go.kr 변경분 미러링 (필요한 법령만, `reg law targets`). 끝나면 Asset `law_mirror` → reg_process.
내부규정 연계(link)·인용 법령 승격(promote)은 파싱 뒤에 reg_law_link가 한다 (M6-1 순서 계약:
sync_daily → reg_process 뒤 link → promote → reg_process).
본문: `reg.sources.lawgo.tasks` (M6-1).
"""
from datetime import timedelta

from airflow.sdk import dag, task
from reg_common import COLLECT, LAW_MIRROR, cron, dag_kwargs


@dag(schedule=cron("0 1 * * *"), **dag_kwargs(__doc__))
def reg_law_daily():
    @task(pool="lawgo_pool", outlets=[LAW_MIRROR], **{**COLLECT, "execution_timeout": timedelta(minutes=120)})
    def sync_daily() -> dict:
        from reg.sources.lawgo.tasks import sync_daily as run

        return run()

    sync_daily()


reg_law_daily()
