import psycopg
import pytest


@pytest.fixture
def app_dsn(migrated, monkeypatch):
    """ops 함수는 스스로 설정을 읽어 접속한다: 테스트 DB를 REG_DATABASE_URL로 넘긴다."""
    from reg.platform.settings import get_settings

    for k in ("AIRFLOW_CTX_DAG_ID", "AIRFLOW_CTX_DAG_RUN_ID", "AIRFLOW_CTX_TASK_ID"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("REG_DATABASE_URL", migrated[0])
    get_settings.cache_clear()
    yield migrated[0]
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def clean_pipeline_run(migrated):
    with psycopg.connect(migrated[0], autocommit=True) as c:
        c.execute("DELETE FROM ops.pipeline_run")
    yield
