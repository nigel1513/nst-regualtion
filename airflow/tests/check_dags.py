"""Airflow 이미지 안에서 DAG를 점검한다 (scripts/airflow-check.sh가 실행). 주 venv에는 airflow를 넣지 않는다."""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import timedelta
from types import SimpleNamespace

DAGS = os.environ.get("AIRFLOW__CORE__DAGS_FOLDER", "/opt/airflow/dags")
sys.path.insert(0, DAGS)
os.environ["REG_DATABASE_URL"] = "postgresql://nobody:x@127.0.0.1:1/none"  # 콜백 점검: 닿지 않는 DB

try:
    from airflow.dag_processing.dagbag import DagBag
except ImportError:  # pragma: no cover
    from airflow.models.dagbag import DagBag

D = "default_pool"
EXPECTED = {
    "reg_law_daily": {"cron": "0 1 * * *", "tasks": {"sync_daily": ("lawgo_pool", 3)}},
    "reg_law_full": {"cron": "0 0 * * 0", "tasks": {"sync_full": ("lawgo_pool", 2)}},
    "reg_law_link": {"assets": ["regulation_structured"],
                     "tasks": {"link": (D, 2), "promote": (D, 2), "announce": (D, 0)}},
    "reg_alio_daily": {"cron": "0 2 * * *",
                       "tasks": {"institutions": (D, 2), "collect": ("alio_pool", 3), "reconcile": (D, 2),
                                 "done": (D, 0), "watcher": (D, 0)}},
    "reg_process": {"cron": "30 3 * * *", "assets": ["regulation_raw", "law_mirror", "regulation_ocr", "law_promoted"],
                    "tasks": {"process_all": (D, 1), "quality_summary": (D, 1), "annex_render": (D, 1),
                              "annex_tables": ("gpu_pool", 1), "watcher": (D, 0)}},
    "reg_ocr": {"assets": ["regulation_structured"], "tasks": {"run_pending": (D, 2), "announce": (D, 0)}},
    "reg_publish": {"assets": ["regulation_structured"],
                    "tasks": {"graph_sync": (D, 2), "alerts_scan": (D, 2), "embed_check": ("gpu_pool", 6),
                              "index_build": ("gpu_pool", 6), "index_gate": (D, 3), "index_publish": (D, 1),
                              "daily_summary": (D, 1), "watcher": (D, 0)}},
    "reg_notify": {"cron": "5 * * * *", "tasks": {"notify": (D, 2)}},
    "reg_maintenance": {"cron": "0 4 * * *", "tasks": {"maintenance": (D, 1)}},
    "reg_backfill": {"manual": True,
                     "tasks": {"targets": (D, 1), "collect": ("alio_pool", 3), "done": (D, 0), "watcher": (D, 0)}},
}
OUTLETS = {("reg_law_daily", "sync_daily"): "law_mirror", ("reg_law_full", "sync_full"): "law_mirror",
           ("reg_law_link", "announce"): "law_promoted",
           ("reg_alio_daily", "done"): "regulation_raw", ("reg_backfill", "done"): "regulation_raw",
           ("reg_process", "process_all"): "regulation_structured", ("reg_ocr", "announce"): "regulation_ocr"}
TRIGGERS = {("reg_alio_daily", "reconcile"): "all_done", ("reg_alio_daily", "done"): "all_done",
            ("reg_alio_daily", "watcher"): "one_failed", ("reg_backfill", "done"): "all_done",
            ("reg_backfill", "watcher"): "one_failed", ("reg_process", "quality_summary"): "all_done",
            ("reg_process", "watcher"): "one_failed", ("reg_publish", "daily_summary"): "all_done",
            ("reg_publish", "watcher"): "one_failed"}
RETRY_DELAY = {("reg_publish", "embed_check"): timedelta(minutes=30),
               ("reg_publish", "index_build"): timedelta(minutes=30)}
BATCH_MODULES = ["reg.platform.runs", "reg.platform.convert", "reg.ops.tasks", "reg.ops.failures", "reg.wiring",
                 "reg.sources.alio.tasks", "reg.sources.lawgo.tasks", "reg.core.ingest.tasks", "reg.ocr.tasks",
                 "reg.graph.tasks", "reg.alerts.tasks", "reg.index.tasks"]
REQUIRED_MODULES = BATCH_MODULES[:5]

errors: list[str] = []


def check(cond, msg: str) -> None:
    if not cond:
        errors.append(msg)


def _inner(tt):
    return getattr(tt, "timetable", tt)


def check_dag(dag, exp: dict) -> None:
    did = dag.dag_id
    check(dag.max_active_runs == 1, f"{did}: max_active_runs={dag.max_active_runs}")
    check(not dag.catchup, f"{did}: catchup이 켜져 있음")
    tt = dag.timetable
    if exp.get("manual"):
        check(type(tt).__name__ == "NullTimetable", f"{did}: 수동 DAG인데 일정 {type(tt).__name__}")
    if "cron" in exp:
        inner = _inner(tt)
        expr = getattr(inner, "expression", None) or getattr(inner, "summary", None)  # 3.3 SDK: expression
        tz = getattr(inner, "timezone", None) or getattr(inner, "_timezone", "")
        check(expr == exp["cron"], f"{did}: cron {expr!r}")
        check("Asia/Seoul" in str(tz), f"{did}: 시간대가 Asia/Seoul이 아님")
    if "assets" in exp:
        cond = repr(getattr(tt, "asset_condition", ""))
        for name in exp["assets"]:
            check(name in cond, f"{did}: Asset 조건에 {name} 없음 ({cond[:200]})")
        if "cron" not in exp:
            check(type(tt).__name__ == "AssetTriggeredTimetable", f"{did}: Asset 트리거가 아님")
    tasks = {t.task_id: t for t in dag.tasks}
    check(set(tasks) == set(exp["tasks"]), f"{did}: 태스크 {sorted(tasks)} ≠ {sorted(exp['tasks'])}")
    for tid, (pool, retries) in exp["tasks"].items():
        t = tasks.get(tid)
        if t is None:
            continue
        check(t.pool == pool, f"{did}.{tid}: pool {t.pool} ≠ {pool}")
        check(t.retries == retries, f"{did}.{tid}: retries {t.retries} ≠ {retries}")
        check(t.execution_timeout is not None, f"{did}.{tid}: execution_timeout 없음")
        if tid != "watcher":
            check(bool(t.on_failure_callback), f"{did}.{tid}: on_failure_callback 없음")
        if tid == "collect":
            check(bool(t.retry_exponential_backoff), f"{did}.{tid}: 지수 백오프 아님")
    for (d, tid), asset in OUTLETS.items():
        if d == did:
            names = [getattr(a, "name", None) for a in (tasks[tid].outlets or [])]
            check(asset in names, f"{did}.{tid}: outlet {names} 에 {asset} 없음")
    for (d, tid), rule in TRIGGERS.items():
        if d == did:
            check(str(getattr(tasks[tid].trigger_rule, "value", tasks[tid].trigger_rule)) == rule,
                  f"{did}.{tid}: trigger_rule {tasks[tid].trigger_rule} ≠ {rule}")
    for (d, tid), delay in RETRY_DELAY.items():
        if d == did:
            check(tasks[tid].retry_delay == delay, f"{did}.{tid}: retry_delay {tasks[tid].retry_delay} ≠ {delay}")


def expect_skip(fn, arg, msg: str) -> None:
    from reg_common import AirflowSkipException

    try:
        fn(arg)
    except AirflowSkipException:
        return
    except Exception as e:
        errors.append(f"{msg} (다른 예외: {e!r})")
        return
    errors.append(msg)


def check_callables(bag) -> None:
    pub = bag.dags["reg_publish"].task_dict
    expect_skip(pub["index_gate"].python_callable, {"skipped": "변화 없음"}, "index_gate: release_id 없을 때 건너뛰지 않음")
    ocr = bag.dags["reg_ocr"].task_dict
    expect_skip(ocr["announce"].python_callable, {"processed": 0}, "announce: 처리 0건인데 건너뛰지 않음")
    expect_skip(ocr["announce"].python_callable, {}, "announce: processed 키가 없을 때 건너뛰지 않음")
    check(ocr["announce"].python_callable({"processed": 2}) == {"processed": 2}, "announce: 처리 건을 넘기지 않음")
    law = bag.dags["reg_law_link"].task_dict
    expect_skip(law["announce"].python_callable, {"emitted": 0}, "reg_law_link.announce: 승격 0건인데 건너뛰지 않음")
    expect_skip(law["announce"].python_callable, {}, "reg_law_link.announce: emitted 키가 없을 때 건너뛰지 않음")
    check(law["announce"].python_callable({"emitted": 1}) == {"emitted": 1}, "reg_law_link.announce: 승격 건을 넘기지 않음")
    rec = bag.dags["reg_alio_daily"].task_dict["reconcile"].python_callable([None, None])
    check(rec == {"skipped": "정상 종료된 기관 없음"}, f"reconcile: 정상 종료 기관이 없을 때 {rec!r}")


def check_failure_callback() -> None:
    import reg_common

    ctx = {"ti": SimpleNamespace(dag_id="reg_x", run_id="manual__1", task_id="t", map_index=3, try_number=4),
           "exception": ValueError("boom")}
    f = reg_common.failure_fields(ctx)
    check(f == {"dag_id": "reg_x", "run_id": "manual__1", "task_id": "t", "map_index": 3, "try_number": 4,
                "error": "ValueError: boom"}, f"failure_fields: {f}")
    try:
        reg_common.record_failure(ctx)
    except Exception as e:
        errors.append(f"record_failure가 DB 장애 때 예외를 냄: {e!r}")


def check_environment() -> None:
    code = (
        "import importlib, sys\n"
        f"mods, required = {BATCH_MODULES!r}, {REQUIRED_MODULES!r}\n"
        "missing = []\n"
        "for m in mods:\n"
        "    try:\n"
        "        importlib.import_module(m)\n"
        "    except ModuleNotFoundError as e:\n"
        "        if not (e.name or '').startswith('reg'):\n"
        "            raise\n"
        "        missing.append(m)\n"
        "assert not set(missing) & set(required), f'필수 모듈 없음: {missing}'\n"
        "from reg.wiring import register_sources\n"
        "register_sources()  # reg_process.process_all이 먼저 부른다\n"
        "print('아직 없는 모듈(다른 트랙):', missing)\n"
        "assert 'fastapi' not in sys.modules, 'fastapi가 배치 import 경로에 들어옴'\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    print(r.stdout.strip())
    check(r.returncode == 0, f"배치 모듈 import 실패: {r.stderr.strip()[-500:]}")
    r = subprocess.run([sys.executable, "-m", "pip", "check"], capture_output=True, text=True, check=False)
    bad = [line for line in r.stdout.splitlines()
           if line.strip() and not line.startswith("nst-regulation ") and "No broken requirements" not in line]
    check(not bad, f"pip check: {bad}")
    try:
        import airflow.providers.fab  # noqa: F401
    except ImportError:
        errors.append("FAB 제공자가 없음 (AIRFLOW__CORE__AUTH_MANAGER)")
    from zoneinfo import ZoneInfo

    ZoneInfo("Asia/Seoul")


def main() -> int:
    bag = DagBag(dag_folder=DAGS)  # 예제는 AIRFLOW__CORE__LOAD_EXAMPLES=false로 끈다 (3.3: include_examples 인자 없음)
    for f, e in bag.import_errors.items():
        errors.append(f"import 오류 {f}: {e}")
    check(set(bag.dags) == set(EXPECTED), f"dag_id {sorted(bag.dags)} ≠ {sorted(EXPECTED)}")
    for dag_id, exp in EXPECTED.items():
        if dag_id in bag.dags:
            check_dag(bag.dags[dag_id], exp)
    if not bag.import_errors and set(bag.dags) == set(EXPECTED):
        check_callables(bag)
    check_failure_callback()
    check_environment()
    if errors:
        print("DAG 점검 실패:")
        for e in errors:
            print(" -", e)
        return 1
    print(f"DAG 점검 통과: {len(bag.dags)}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())
