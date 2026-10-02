"""알림 (매시 05분 KST, spec §1): change_impact → notification → 메일 (높음 즉시, 그 밖 하루 묶음)."""
from datetime import timedelta

from airflow.sdk import dag, task
from reg_common import cron, dag_kwargs


@dag(schedule=cron("5 * * * *"), **dag_kwargs(__doc__))
def reg_notify():
    @task(retries=2, retry_delay=timedelta(minutes=5), execution_timeout=timedelta(minutes=20))
    def notify() -> dict:
        from reg.alerts.tasks import notify as run

        return run()

    notify()


reg_notify()
