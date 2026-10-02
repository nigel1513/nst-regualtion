from datetime import timedelta

from typer.testing import CliRunner

from reg.cli import app
from reg.sources.alio import tasks
from tests.sources.alio.seed import T0, add_inst, add_rule

runner = CliRunner()


def test_abolish_confirm_reject_and_error(app_env, conn):
    inst = add_inst(conn)
    wid = add_rule(conn, inst, "1", T0 - timedelta(days=5))
    conn.execute("UPDATE regulation.alio_rule SET missing_since = '2026-09-28', abolish_state = 'CANDIDATE' WHERE seq = '1'")
    conn.commit()
    r = runner.invoke(app, ["alio", "abolish", wid])
    assert r.exit_code == 0 and "ABOLISHED" in r.output and "2026-09-28" in r.output
    r = runner.invoke(app, ["alio", "abolish", wid, "--reject"])
    assert r.exit_code == 0 and "ACTIVE" in r.output
    r = runner.invoke(app, ["alio", "abolish", wid])
    assert r.exit_code == 1 and "폐지 후보가 아닙니다" in r.output


def test_reconcile_and_backfill_commands(app_env, conn, monkeypatch):
    r = runner.invoke(app, ["alio", "reconcile"])
    assert r.exit_code == 0 and "projection" in r.output
    got = []
    monkeypatch.setattr(tasks, "backfill", lambda code: got.append(code) or {"collect": {}, "reconcile": {}})
    r = runner.invoke(app, ["alio", "backfill", "--institution", "KBSI"])
    assert r.exit_code == 0 and got == ["KBSI"] and "reg process --all" in r.output
