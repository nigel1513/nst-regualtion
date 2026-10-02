import json

from typer.testing import CliRunner

from reg.ops import cli, tasks


def test_summary_and_maintenance_commands(monkeypatch):
    monkeypatch.setattr(tasks, "daily_summary", lambda day=None: {"day": day or "today"})
    monkeypatch.setattr(tasks, "maintenance", lambda: {"request_log_deleted": 0})
    r = CliRunner().invoke(cli.app, ["summary", "--day", "2026-10-02"])
    assert r.exit_code == 0 and json.loads(r.stdout) == {"day": "2026-10-02"}
    r = CliRunner().invoke(cli.app, ["maintenance"])
    assert r.exit_code == 0 and json.loads(r.stdout) == {"request_log_deleted": 0}
