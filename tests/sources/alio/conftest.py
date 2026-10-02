import pytest

from reg.platform.settings import get_settings


@pytest.fixture
def app_env(monkeypatch, migrated):
    """tasks·CLI가 스스로 설정을 읽어 테스트 DB에 붙게 한다."""
    monkeypatch.setenv("REG_DATABASE_URL", migrated[0])
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _no_canary(monkeypatch):
    """active_institutions·backfill이 테스트 중 실제 ALIO에 요청하지 않게 한다 (점검 자체는 test_canary.py가 run_canary로 시험)."""
    from reg.sources.alio import tasks

    if hasattr(tasks, "canary_check"):
        monkeypatch.setattr(tasks, "canary_check", lambda: {"ok": True, "stub": True})
