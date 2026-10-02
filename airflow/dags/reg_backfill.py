"""백필 (수동, spec §9): 신규 기관 전체 수집.

Trigger 시 conf 예: {"institutions": ["KAERI"]}. 기관은 먼저 config에 추가해 활성 목록에 있어야 한다.
수집이 끝나면 Asset `regulation_raw` → 파싱·게시가 이어서 돈다. 파서 변경 후 전체 재파싱은 CLI `reg process --rebuild`.
"""
from airflow.sdk import Param, dag, get_current_context, task
from reg_common import COLLECT, MARK, ONCE, RAW, dag_kwargs, watcher


@dag(schedule=None,
     params={"institutions": Param([], type="array", items={"type": "string"},
                                   description="수집할 기관 코드 목록 (예: [\"KAERI\"])")},
     **dag_kwargs(__doc__))
def reg_backfill():
    @task(**ONCE)
    def targets() -> list[str]:
        wanted = [str(c).strip() for c in (get_current_context()["params"].get("institutions") or []) if str(c).strip()]
        if not wanted:
            raise ValueError('conf.institutions에 기관 코드를 하나 이상 넣으세요 (예: {"institutions": ["KAERI"]})')
        from reg.sources.alio.tasks import active_institutions

        unknown = sorted(set(wanted) - set(active_institutions()))
        if unknown:
            raise ValueError(f"활성 기관이 아님: {unknown} — config에 추가했는지 확인하세요")
        return wanted

    @task(pool="alio_pool", **COLLECT)
    def collect(code: str) -> dict:
        from reg.sources.alio.tasks import collect_institution

        return collect_institution(code)

    @task(trigger_rule="all_done", outlets=[RAW], **MARK)
    def done() -> None:
        return None

    codes = targets()
    results = collect.expand(code=codes)
    fin = done()
    results >> fin
    [codes, results, fin] >> watcher()


reg_backfill()
