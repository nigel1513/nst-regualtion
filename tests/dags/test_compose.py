"""compose 정의 검사: `docker compose config`만 실행한다(아무것도 띄우지 않음)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
AIRFLOW = ("airflow-init", "airflow-apiserver", "airflow-scheduler", "airflow-dag-processor")


@pytest.fixture(scope="module")
def cfg():
    if shutil.which("docker") is None:
        pytest.skip("docker 없음")
    r = subprocess.run(["docker", "compose", "--env-file", ".env.example", "-f", "infra/docker-compose.yml",
                        "config", "--format", "json"], cwd=ROOT, capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_existing_services_kept(cfg):
    assert {"storage", "opensearch-proxy", "neo4j", "mailpit-proxy", "converter", *AIRFLOW} <= set(cfg["services"])


def test_apiserver_on_21062(cfg):
    ports = cfg["services"]["airflow-apiserver"]["ports"]
    assert [(str(p["published"]), p["target"]) for p in ports] == [("21062", 8080)]


def test_converter_is_internal_only(cfg):
    c = cfg["services"]["converter"]
    assert "ports" not in c and set(c["networks"]) == {"convert"}
    assert c["entrypoint"] == ["python3", "/srv/converter/server.py"]
    assert cfg["networks"]["convert"]["internal"] is True


@pytest.mark.parametrize("svc", AIRFLOW)
def test_airflow_env_and_networks(cfg, svc):
    s = cfg["services"][svc]
    env = s["environment"]
    assert set(s["networks"]) == {"default", "nais", "convert"}
    assert env["AIRFLOW__CORE__EXECUTOR"] == "LocalExecutor"
    assert env["AIRFLOW__CORE__DEFAULT_TIMEZONE"] == "Asia/Seoul"
    assert env["AIRFLOW__DATABASE__SQL_ALCHEMY_CONN"].endswith("@postgres:5432/reg_airflow")
    assert env["AIRFLOW__CORE__EXECUTION_API_SERVER_URL"] == "http://airflow-apiserver:8080/execution/"
    assert env["REG_DATABASE_URL"].split("@")[1].startswith("postgres:5432/")
    assert env["REG_S3_ENDPOINT"] == "http://storage:8333"
    assert env["REG_OS_URL"] == "http://opensearch:9200"
    assert env["REG_NEO4J_URL"] == "bolt://neo4j:7687"
    assert (env["REG_SMTP_HOST"], env["REG_SMTP_PORT"]) == ("mailpit", "1025")
    assert env["REG_CONVERTER_URL"] == "http://converter:8080"
    assert env["REG_AIRFLOW_LOG_DIR"] == "/opt/airflow/logs"
    mounts = {v["target"]: v for v in s["volumes"]}
    assert mounts["/opt/airflow/dags"]["read_only"] and mounts["/opt/nst-regulation/config"]["read_only"]
    assert mounts["/opt/airflow/logs"]["type"] == "volume"


def test_scheduler_waits_for_init(cfg):
    dep = cfg["services"]["airflow-scheduler"]["depends_on"]
    assert dep["airflow-init"]["condition"] == "service_completed_successfully"
