"""GPU를 쓰는 태스크는 모두 gpu_pool(슬롯 1)에 묶인다 — MinerU OCR과 임베딩이 GPU 한 대를 동시에 쓰지 않게."""
import ast
from pathlib import Path

DAGS = Path(__file__).resolve().parents[2] / "airflow" / "dags"


def _task_pools(dag_file: str) -> dict[str, str | None]:
    out = {}
    for fn in ast.walk(ast.parse((DAGS / dag_file).read_text(encoding="utf-8"))):
        if not isinstance(fn, ast.FunctionDef):
            continue
        for d in fn.decorator_list:
            if isinstance(d, ast.Call) and getattr(d.func, "id", getattr(d.func, "attr", None)) == "task":
                pool = next((k.value.value for k in d.keywords if k.arg == "pool"), None)
                out[fn.name] = pool
    return out


def test_ocr_runs_in_the_gpu_pool():
    assert _task_pools("reg_ocr.py")["run_pending"] == "gpu_pool"
