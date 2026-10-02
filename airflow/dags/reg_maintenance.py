"""정리 (매일 04:00 KST, spec §8): request_log 90일·qa_log 365일·Airflow 로그 30일, 옛 release 색인(M6-4 prune)."""
from datetime import timedelta

from airflow.sdk import dag, task
from reg_common import ONCE, cron, dag_kwargs


@dag(schedule=cron("0 4 * * *"), **dag_kwargs(__doc__))
def reg_maintenance():
    @task(**{**ONCE, "execution_timeout": timedelta(minutes=60)})
    def maintenance() -> dict:
        from reg.ops.tasks import maintenance as run

        return run()

    maintenance()


reg_maintenance()
