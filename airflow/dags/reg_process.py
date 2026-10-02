"""파싱·적재 (Asset regulation_raw | law_mirror | regulation_ocr | law_promoted 갱신 시 + 매일 03:30 KST 안전망, spec §4)

outbox 소비 → 추출·구조·시행일·적재 → 품질 집계. 성공하면 Asset `regulation_structured` → reg_publish, reg_ocr, reg_law_link.
"""
from airflow.sdk import dag, task
from reg_common import (
    LAW_MIRROR,
    LAW_PROMOTED,
    OCR_DONE,
    ONCE,
    PARSE,
    RAW,
    STRUCTURED,
    cron_or_assets,
    dag_kwargs,
    watcher,
)


@dag(schedule=cron_or_assets("30 3 * * *", RAW | LAW_MIRROR | OCR_DONE | LAW_PROMOTED), **dag_kwargs(__doc__))
def reg_process():
    @task(outlets=[STRUCTURED], **PARSE)
    def process_all() -> dict:
        from reg.core.ingest.tasks import process_all as run
        from reg.wiring import register_sources

        register_sources()  # core는 출처를 모른다: 처리기 등록 없이 process_all을 부르면 미등록 topic으로 실패한다
        return run()

    @task(trigger_rule="all_done", **ONCE)
    def quality_summary() -> dict:
        from reg.core.ingest.tasks import quality_summary as run

        return run()

    p = process_all()
    q = quality_summary()
    p >> q
    [p, q] >> watcher()


reg_process()
