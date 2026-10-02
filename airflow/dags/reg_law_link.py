"""법령 연계·승격 (Asset regulation_structured 갱신 시, M6-1 순서 계약)

파싱이 끝난 뒤 내부규정의 법령 인용을 미러에 연결하고(link), 인용된 법령을 규정 저장소로 승격한다(promote).
승격 이벤트가 생겼을 때만 Asset `law_promoted`를 갱신해 reg_process를 다시 깨운다.
승격 건이 없으면 announce를 건너뛴다 → reg_process ↔ reg_law_link 무한 반복이 없다.
"""
from airflow.sdk import dag, task
from reg_common import LAW_PROMOTED, LIGHT, MARK, STRUCTURED, dag_kwargs, skip


@dag(schedule=STRUCTURED, **dag_kwargs(__doc__))
def reg_law_link():
    @task(**LIGHT)
    def link() -> dict:
        from reg.sources.lawgo.tasks import link as run

        return run()

    @task(**LIGHT)
    def promote() -> dict:
        from reg.sources.lawgo.tasks import promote as run

        return run()

    @task(outlets=[LAW_PROMOTED], **MARK)
    def announce(stats: dict) -> dict:
        if int((stats or {}).get("emitted", 0) or 0) == 0:
            skip("승격 이벤트 없음 — reg_process를 다시 깨우지 않는다")
        return stats

    link() >> (p := promote())
    announce(p)


reg_law_link()
