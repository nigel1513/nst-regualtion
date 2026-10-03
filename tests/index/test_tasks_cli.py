import pytest
import yaml
from typer.testing import CliRunner

from reg.index import cli, tasks
from tests.index.fakes import SMOKE_BAD, SMOKE_OK, FakeEmbedder, FakeReranker


@pytest.fixture
def env(loaded, osx, os_url, migrated, tmp_path, monkeypatch):
    from reg.platform.settings import get_settings

    smoke = tmp_path / "smoke.yaml"
    smoke.write_text(yaml.safe_dump(SMOKE_OK, allow_unicode=True), encoding="utf-8")
    monkeypatch.setenv("REG_DATABASE_URL", migrated[0])
    monkeypatch.setenv("REG_OS_URL", os_url)
    monkeypatch.setenv("REG_EMBED_MODEL", "fake")
    monkeypatch.setenv("REG_INDEX_SMOKE", str(smoke))
    monkeypatch.setattr(tasks, "EmbeddingProvider", lambda *a, **k: FakeEmbedder())
    monkeypatch.setattr(tasks, "RerankProvider", lambda *a, **k: FakeReranker())
    get_settings.cache_clear()
    yield {"smoke": smoke, "os": osx}
    get_settings.cache_clear()


def _runs(conn):
    return conn.execute("SELECT count(*) AS n FROM ops.pipeline_run").fetchone()["n"]


def test_airflow_sequence_build_gate_publish_then_skip(env, loaded):
    before = _runs(loaded)
    b = tasks.build()
    assert b["skipped"] is False and env["os"].alias_target() is None      # build는 게시하지 않는다
    assert tasks.gate(b["release_id"])["passed"] is True
    p = tasks.publish(b["release_id"])
    assert p["published"] is True and env["os"].alias_target() == b["index"]
    again = tasks.build()                                                   # 변화 없는 날
    assert again["skipped"] is True and again["release_id"] == b["release_id"]
    assert tasks.gate(again["release_id"])["already_published"] is True     # 후속 태스크도 오류 없이 지나간다
    assert tasks.publish(again["release_id"])["already"] is True
    assert _runs(loaded) >= before + 6                                     # 태스크마다 실행 이력


def test_gate_failure_raises_and_keeps_alias(env):
    first = tasks.build()
    tasks.gate(first["release_id"])
    tasks.publish(first["release_id"])
    env["smoke"].write_text(yaml.safe_dump(SMOKE_BAD, allow_unicode=True), encoding="utf-8")
    b = tasks.build(force=True)
    with pytest.raises(tasks.GateFailed, match="kasi-a999"):
        tasks.gate(b["release_id"])
    assert env["os"].alias_target() == first["index"]


def test_embed_check_and_prune(env, monkeypatch):
    assert tasks.embed_check() is True
    monkeypatch.setattr(tasks, "EmbeddingProvider", lambda *a, **k: FakeEmbedder(fail_after=0))
    assert tasks.embed_check() is False
    assert tasks.prune()["deleted"] == []


def test_cli_build_runs_gate_then_publish(monkeypatch):
    calls = []
    monkeypatch.setattr(tasks, "build", lambda force=False: calls.append(("build", force)) or
                        {"skipped": False, "release_id": 7, "index": "reg-provisions-r7", "chunks": 1})
    monkeypatch.setattr(tasks, "gate", lambda rid: calls.append(("gate", rid)) or {"passed": True, "reasons": []})
    monkeypatch.setattr(tasks, "publish", lambda rid: calls.append(("publish", rid)) or {"published": True})
    r = CliRunner().invoke(cli.index, ["build", "--force"])
    assert r.exit_code == 0, r.output
    assert calls == [("build", True), ("gate", 7), ("publish", 7)]


def test_cli_build_stops_on_gate_failure_and_skip(monkeypatch):
    monkeypatch.setattr(tasks, "build", lambda force=False: {"skipped": False, "release_id": 8})

    def bad(rid):
        raise tasks.GateFailed("release 8 품질 게이트 실패: 스모크 실패: x")
    monkeypatch.setattr(tasks, "gate", bad)
    monkeypatch.setattr(tasks, "publish", lambda rid: pytest.fail("게이트 실패 후 게시하면 안 된다"))
    assert CliRunner().invoke(cli.index, ["build"]).exit_code == 1
    monkeypatch.setattr(tasks, "build", lambda force=False: {"skipped": True, "release_id": 3})
    monkeypatch.setattr(tasks, "gate", lambda rid: pytest.fail("건너뛴 날은 게이트를 보지 않는다"))
    r = CliRunner().invoke(cli.index, ["build"])
    assert r.exit_code == 0 and "변화 없음" in r.output


def test_cli_no_publish(monkeypatch):
    monkeypatch.setattr(tasks, "build", lambda force=False: {"skipped": False, "release_id": 9})
    monkeypatch.setattr(tasks, "gate", lambda rid: {"passed": True, "reasons": []})
    monkeypatch.setattr(tasks, "publish", lambda rid: pytest.fail("--no-publish"))
    assert CliRunner().invoke(cli.index, ["build", "--no-publish"]).exit_code == 0
