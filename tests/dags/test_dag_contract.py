"""DAG 파일 계약: 최상위에서 reg를 import하지 않고, 태스크 안에서는 overview §2.6 표의 함수만 부른다."""
import ast
from pathlib import Path

DAGS = Path(__file__).resolve().parents[2] / "airflow" / "dags"
DAG_IDS = {"reg_law_daily", "reg_law_full", "reg_law_link", "reg_alio_daily", "reg_process", "reg_publish", "reg_ocr",
           "reg_notify", "reg_maintenance", "reg_backfill"}
ALLOWED = {
    "reg.sources.alio.tasks": {"active_institutions", "collect_institution", "reconcile"},
    "reg.sources.lawgo.tasks": {"sync_daily", "sync_full", "link", "promote"},
    "reg.core.ingest.tasks": {"process_all", "quality_summary"},
    "reg.ocr.tasks": {"run_pending"},
    "reg.graph.tasks": {"sync"},
    "reg.alerts.tasks": {"scan", "notify"},
    "reg.index.tasks": {"embed_check", "build", "gate", "publish", "prune", "GateFailed"},  # 품질 미달 예외 (재시도 없이 실패)
    "reg.ops.tasks": {"daily_summary", "maintenance"},
    "reg.ops.failures": {"record_task_failure"},   # M6-3 자체 실패 콜백
    "reg.wiring": {"register_sources"},            # process_all 전에 출처 처리기 등록 (M6-0 ruling)
}


def _is_reg(mod: str | None) -> bool:
    return bool(mod) and (mod == "reg" or mod.startswith("reg."))


def _module_level(nodes):
    for n in nodes:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        yield n
        for field in ("body", "orelse", "finalbody", "handlers"):
            yield from _module_level(getattr(n, field, None) or [])


def _trees():
    return {p.stem: ast.parse(p.read_text(encoding="utf-8")) for p in sorted(DAGS.glob("*.py"))}


def test_dag_files_present():
    assert set(_trees()) == DAG_IDS | {"reg_common"}
    assert (DAGS / ".airflowignore").read_text().split() == ["reg_common.py"]


def test_no_reg_import_at_module_level():
    for name, tree in _trees().items():
        for n in _module_level(tree.body):
            if isinstance(n, ast.ImportFrom):
                assert not _is_reg(n.module), f"{name}: 최상위 import {n.module}"
            if isinstance(n, ast.Import):
                assert not any(_is_reg(a.name) for a in n.names), f"{name}: 최상위 import"


def test_lazy_imports_follow_contract():
    for name, tree in _trees().items():
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                assert not any(_is_reg(a.name) for a in n.names), f"{name}: 'import reg…' 대신 from-import"
            if isinstance(n, ast.ImportFrom) and _is_reg(n.module):
                assert n.module in ALLOWED, f"{name}: 계약 밖 모듈 {n.module}"
                names = {a.name for a in n.names}
                assert names <= ALLOWED[n.module], f"{name}: 계약 밖 함수 {names - ALLOWED[n.module]}"


def test_each_file_defines_and_instantiates_its_dag():
    for dag_id in DAG_IDS:
        tree = _trees()[dag_id]
        funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
        assert [f.name for f in funcs] == [dag_id]
        assert any(isinstance(d, ast.Call) and getattr(d.func, "id", "") == "dag" for d in funcs[0].decorator_list)
        last = tree.body[-1]
        assert isinstance(last, ast.Expr) and isinstance(last.value, ast.Call) and last.value.func.id == dag_id


def test_process_all_registers_sources_first():
    tree = _trees()["reg_process"]
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "process_all")
    calls = [n.func.id for stmt in fn.body for n in ast.walk(stmt)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    assert calls[:2] == ["register_sources", "run"], calls
