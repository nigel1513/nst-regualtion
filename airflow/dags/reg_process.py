"""파싱·적재 (Asset regulation_raw | law_mirror | regulation_ocr | law_promoted 갱신 시 + 매일 03:30 KST 안전망, spec §4)

outbox 소비 → 추출·구조·시행일·적재 → 참조 재해석 → 품질 집계.
참조 재해석까지 성공하면 Asset `regulation_structured` → reg_publish(graph_sync 증분이 재해석 결과까지 반영), reg_ocr, reg_law_link.
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
    @task(**PARSE)
    def process_all() -> dict:
        from reg.core.ingest.tasks import process_all as run
        from reg.wiring import register_sources

        register_sources()  # core는 출처를 모른다: 처리기 등록 없이 process_all을 부르면 미등록 topic으로 실패한다
        return run()

    @task(outlets=[STRUCTURED], **PARSE)
    def refs_reresolve(processed: dict) -> dict:
        """먼저 처리된 규정이 이번에 적재된 규정을 가리킨 참조를 다시 해석한다. 바뀐 work만 다시 쓴다."""
        from reg.core.ingest.tasks import reresolve_refs

        return reresolve_refs(processed)

    @task(trigger_rule="all_done", **ONCE)
    def quality_summary() -> dict:
        from reg.core.ingest.tasks import quality_summary as run

        return run()

    @task(**ONCE)
    def annex_render() -> dict:
        """새로 적재된 현행 버전의 별표 영역을 PNG로 미리 만든다 (M6-6, CPU)."""
        from reg.core.annex_tasks import render_current

        return render_current()

    @task(pool="gpu_pool", **ONCE)
    def annex_tables() -> dict:
        """별표 표를 MinerU로 HTML 변환 (M6-6). GPU PC가 꺼져 있으면 건너뛰고 다음 실행에서 다시 한다."""
        from reg.core.annex_tasks import convert_tables

        return convert_tables()

    p = process_all()
    rr = refs_reresolve(p)
    q = quality_summary()
    r = annex_render()
    t = annex_tables()
    rr >> q
    p >> r >> t
    [p, rr, q, r, t] >> watcher()


reg_process()
