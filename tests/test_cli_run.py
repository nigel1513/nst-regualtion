import pytest

from reg import cli
from reg.platform.settings import get_settings


@pytest.fixture
def app_env(monkeypatch, migrated):
    monkeypatch.setenv("REG_DATABASE_URL", migrated[0])
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_interrupted_run_is_marked_failed(app_env, conn):
    def body(c, log):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        cli._run("alio", None, body)
    r = conn.execute("SELECT status, error FROM regulation.fetch_run ORDER BY id DESC LIMIT 1").fetchone()
    assert r["status"] == "failed" and "KeyboardInterrupt" in r["error"]
