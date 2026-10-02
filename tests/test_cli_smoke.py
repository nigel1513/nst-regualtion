from typer.testing import CliRunner

from reg.cli import app


def test_help_lists_commands():
    out = CliRunner().invoke(app, ["--help"]).output
    for cmd in ("db", "bucket", "collect"):
        assert cmd in out


def test_collect_help():
    out = CliRunner().invoke(app, ["collect", "--help"]).output
    assert "alio" in out and "law" in out
