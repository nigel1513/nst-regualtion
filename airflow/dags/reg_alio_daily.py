"""ALIO 내부규정 일 배치 (매일 02:00 KST, spec §3.1·§3.3)

활성 기관 목록 → 기관별 수집(alio_pool=2) → 폐지 대조(정상 종료 기관만) → Asset `regulation_raw`.
한 기관이 실패해도 받은 파일은 파싱으로 넘어가고(done: all_done), 실행은 실패로 표시된다(watcher).
"""
from airflow.sdk import dag, task
from reg_common import COLLECT, LIGHT, MARK, RAW, cron, dag_kwargs, watcher


@dag(schedule=cron("0 2 * * *"), **dag_kwargs(__doc__))
def reg_alio_daily():
    @task(**LIGHT)
    def institutions() -> list[str]:
        from reg.sources.alio.tasks import active_institutions

        return active_institutions()

    @task(pool="alio_pool", **COLLECT)
    def collect(code: str) -> dict:
        from reg.sources.alio.tasks import collect_institution

        return collect_institution(code)

    @task(trigger_rule="all_done", **LIGHT)
    def reconcile(results: list) -> dict:
        finished = [r for r in (results or []) if r]
        if not finished:  # 정상 종료된 기관이 없으면 폐지 대조를 하지 않는다 (멀쩡한 규정을 사라진 것으로 보지 않게)
            return {"skipped": "정상 종료된 기관 없음"}
        from reg.sources.alio.tasks import reconcile as run

        return run(finished)

    @task(trigger_rule="all_done", outlets=[RAW], **MARK)
    def done() -> None:
        return None

    codes = institutions()
    results = collect.expand(code=codes)
    rec = reconcile(results)
    fin = done()
    rec >> fin
    [codes, results, rec, fin] >> watcher()


reg_alio_daily()
