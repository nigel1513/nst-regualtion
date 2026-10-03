"""Airflow 진입점과 CLI (설정 DSN = 테스트 DB). 추출은 가짜로 바꾼다."""
import pytest
from typer.testing import CliRunner

from reg.cli import app
from reg.compare import build as B
from reg.compare import tasks
from reg.compare.extract import Cell
from tests.compare.test_api_store import seeded, wid  # noqa: F401  (픽스처)


@pytest.fixture
def env(seeded, migrated, monkeypatch):  # noqa: F811
    from reg.platform.settings import get_settings

    monkeypatch.setenv("REG_DATABASE_URL", migrated[0])
    monkeypatch.setattr(B, "candidates", lambda *a, **k: ["c"])
    monkeypatch.setattr(B, "extract", lambda llm, item, inst, cands: Cell(item.topic, item.id, inst, "llm", wid(inst),
                                                                         None, None, "a27.p1", "7일", "7일", "q", 0.9))
    get_settings.cache_clear()
    yield seeded
    get_settings.cache_clear()


def test_classify_then_build_changed_only(env):
    out = tasks.classify_topics()
    assert out["works"] == 4 and out["by_method"] == {"title": 4} and out["rows"] == 4
    assert tasks.classify_topics()["works"] == 0                           # 새 규정이 없으면 할 일 없음
    b = tasks.build_compare(changed_only=True, topics=["travel"])
    assert b["institutions"] == 5 and b["values"] == 20 and b["absent"] == 5   # KBSI는 여비 규정이 없다
    assert tasks.build_compare(changed_only=True) == {"skipped": True, "institutions": 0}
    runs = env.execute("SELECT task_id, status FROM ops.pipeline_run ORDER BY id").fetchall()
    assert [r["task_id"] for r in runs] == ["compare.classify", "compare.classify", "compare.build", "compare.build"]
    assert {r["status"] for r in runs} == {"success"}


def test_cli_dry_runs_do_not_write(env):
    r = CliRunner().invoke(app, ["topics", "classify", "--dry-run"])
    assert r.exit_code == 0, r.output
    assert "'works': 4" in r.output
    assert env.execute("SELECT count(*) n FROM regulation.work_topic").fetchone()["n"] == 0
    from reg.compare.store import save_topics

    save_topics(env, {wid("KASI"): [("travel", 1.0, "title")]})
    r = CliRunner().invoke(app, ["compare", "build", "--dry-run", "--topic", "travel", "--inst", "KASI"])
    assert r.exit_code == 0, r.output
    assert "travel\tevidence_deadline\tKASI\tllm\t7일" in r.output
    assert env.execute("SELECT count(*) n FROM regulation.compare_cell").fetchone()["n"] == 0
    assert CliRunner().invoke(app, ["compare", "build", "--topic", "nope", "--dry-run"]).exit_code != 0
