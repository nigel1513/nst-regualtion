import json

import pytest

from reg.platform.settings import get_settings
from reg.sources.lawgo import tasks
from reg.sources.lawgo.errors import LawGoError, ResponseChanged
from tests.sources.lawgo.helpers import FakeClient, law_list


@pytest.fixture
def env(monkeypatch, migrated, lconn, blob):
    monkeypatch.setenv("REG_DATABASE_URL", migrated[0])
    monkeypatch.setenv("REG_LAWGO_OC", "test")
    get_settings.cache_clear()
    fake = FakeClient()
    monkeypatch.setattr(tasks, "blob_store", lambda s=None: blob)
    monkeypatch.setattr(tasks, "make_client", lambda *a, **k: fake)
    yield fake, lconn
    get_settings.cache_clear()


def _runs(conn) -> dict:
    conn.rollback()
    return {r["task_id"]: r["status"] for r in conn.execute("SELECT task_id, status FROM ops.pipeline_run").fetchall()}


def test_link_and_promote_return_json_and_record_runs(env):
    _, conn = env
    st = tasks.link()
    assert json.dumps(st) and st["refs"] == 0
    st = tasks.promote()
    assert json.dumps(st) and st["emitted"] == 0
    assert _runs(conn) == {"lawgo.link": "success", "lawgo.promote": "success"}


def test_sync_daily_without_full_fails_clearly(env):
    _, conn = env
    with pytest.raises(LawGoError, match="sync_full"):
        tasks.sync_daily()
    assert _runs(conn)["lawgo.sync_daily"] == "failed"
    assert conn.execute("SELECT status FROM ops.fetch_run WHERE source = 'lawgo'").fetchone()["status"] == "failed"


def test_canary_stops_daily_before_any_body_request(env):
    fake, conn = env
    fake.lists[("law", 1, None)] = law_list([], total=3)
    with pytest.raises(ResponseChanged, match="totalCnt=3"):
        tasks.sync_daily("2026-10-01")
    assert not [c for c in fake.calls if c[0] == "service"]
    conn.rollback()
    assert conn.execute("SELECT status FROM law.sync_run").fetchone()["status"] == "failed"


def test_cli_lists_law_commands():
    from typer.testing import CliRunner

    from reg.cli import app

    out = CliRunner().invoke(app, ["law", "--help"]).output
    for cmd in ("sync", "full", "link", "promote", "annex", "status", "collect"):
        assert cmd in out
