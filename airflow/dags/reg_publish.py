"""게시 (Asset regulation_structured 갱신 시, spec §6·§7·§9)

graph_sync → alerts_scan  /  embed_check → index_build → index_gate → index_publish  (두 사슬은 서로 기다리지 않음)
→ daily_summary (all_done). GPU가 꺼져 있으면 embed_check가 30분 간격 6회 재시도하고, 검색은 이전 release로 동작한다.
"""
from airflow.sdk import dag, task
from reg_common import GATE, INDEX, LIGHT, ONCE, STRUCTURED, dag_kwargs, skip, watcher


@dag(schedule=STRUCTURED, **dag_kwargs(__doc__))
def reg_publish():
    @task(**LIGHT)
    def graph_sync() -> dict:
        from reg.graph.tasks import sync

        return sync()

    @task(**LIGHT)
    def alerts_scan() -> dict:
        from reg.alerts.tasks import scan

        return scan()

    @task(pool="gpu_pool", **{**INDEX, "execution_timeout": INDEX["retry_delay"] / 6})
    def embed_check() -> bool:
        from reg.index.tasks import embed_check as check

        if not check():
            raise RuntimeError("GPU 임베딩 서버(REG_EMBED_URL)가 응답하지 않음 — 30분 뒤 다시 확인")
        return True

    @task(pool="gpu_pool", **INDEX)
    def index_build(ready: bool) -> dict:
        from reg.index.tasks import build

        return build()

    @task(**GATE)
    def index_gate(built: dict) -> int:
        rid = (built or {}).get("release_id")
        if rid is None:
            skip("새 release 없음 (변화 없는 날)")
        from airflow.exceptions import AirflowFailException

        from reg.index.tasks import GateFailed, gate

        try:
            gate(int(rid))  # 게이트 불통과는 예외로 알린다 (overview §2.6)
        except GateFailed as e:  # 품질 미달은 다시 해도 같다 → 재시도 없이 실패 (release는 FAILED로 남음)
            raise AirflowFailException(str(e)) from e
        return int(rid)

    @task(**ONCE)
    def index_publish(release_id: int) -> dict:
        from reg.index.tasks import publish

        return publish(release_id)

    @task(trigger_rule="all_done", **ONCE)
    def daily_summary() -> dict:
        from reg.ops.tasks import daily_summary as summarize

        return summarize()

    g = graph_sync()
    s = alerts_scan()
    e = embed_check()
    b = index_build(e)
    gt = index_gate(b)
    p = index_publish(gt)
    summary = daily_summary()
    g >> s
    [s, p] >> summary
    [g, s, e, b, gt, p, summary] >> watcher()


reg_publish()
