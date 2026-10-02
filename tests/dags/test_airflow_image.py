import re
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
AIRFLOW_VERSION = "3.3.2"
NOT_IN_AIRFLOW = {"fastapi", "uvicorn"}  # Airflow 3.3.2는 fastapi<0.137을 요구한다: reg API용 의존성은 넣지 않는다


def _names(lines) -> set[str]:
    out = set()
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#"):
            out.add(re.match(r"[A-Za-z0-9_.-]+", line).group(0).lower().replace("_", "-"))
    return out


def test_batch_requirements_cover_pyproject():
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["dependencies"]
    batch = (ROOT / "infra/airflow/requirements-batch.txt").read_text().splitlines()
    missing = _names(deps) - _names(batch) - NOT_IN_AIRFLOW
    assert not missing, f"pyproject에 추가된 의존성을 infra/airflow/requirements-batch.txt에도 넣으세요: {missing}"


def test_airflow_version_is_pinned_everywhere():
    df = (ROOT / "infra/airflow/Dockerfile").read_text()
    assert re.findall(r"ARG AIRFLOW_VERSION=(\S+)", df) == [AIRFLOW_VERSION, AIRFLOW_VERSION]
    assert "FROM apache/airflow:${AIRFLOW_VERSION}-python${PYTHON_VERSION}" in df
    compose = yaml.safe_load((ROOT / "infra/docker-compose.yml").read_text())
    assert compose["x-airflow-common"]["image"] == f"nst-regulation/airflow:{AIRFLOW_VERSION}"


def test_init_script_creates_pools():
    sh = (ROOT / "infra/airflow/init.sh").read_text()
    for pool, slots in (("alio_pool", 2), ("lawgo_pool", 1), ("gpu_pool", 1)):
        assert f"airflow pools set {pool} {slots} " in sh
    assert "airflow db migrate" in sh and "--role Admin" in sh
