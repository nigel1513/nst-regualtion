"""OCR (Asset regulation_structured 갱신 시, M6-5)

LOW_TEXT 문서를 OCR한다. 처리 건이 있을 때만 Asset `regulation_ocr`를 갱신해 reg_process를 다시 깨운다.
처리 건이 없으면 announce를 건너뛴다 → reg_process ↔ reg_ocr 무한 반복이 없다.
"""
from datetime import timedelta

from airflow.sdk import dag, task
from reg_common import MARK, OCR_DONE, STRUCTURED, dag_kwargs, skip


@dag(schedule=STRUCTURED, **dag_kwargs(__doc__))
def reg_ocr():
    # MinerU는 GPU PC를 임베딩·답변 생성과 나눠 쓴다: gpu_pool(슬롯 1)로 GPU 작업이 겹치지 않게
    @task(pool="gpu_pool", retries=2, retry_delay=timedelta(minutes=10), execution_timeout=timedelta(minutes=120))
    def run_pending() -> dict:
        from reg.ocr.tasks import run_pending as run

        return run(limit=50)

    @task(outlets=[OCR_DONE], **MARK)
    def announce(stats: dict) -> dict:
        if int((stats or {}).get("processed", 0) or 0) == 0:
            skip("OCR 처리 건 없음 — reg_process를 다시 깨우지 않는다")
        return stats

    announce(run_pending())


reg_ocr()
