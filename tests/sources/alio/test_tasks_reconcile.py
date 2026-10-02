import json
from datetime import timedelta

import pytest

from reg.sources.alio import tasks
from tests.sources.alio.seed import T0, add_inst, add_rule, rule


def test_reconcile_task_ignores_incomplete_and_none(app_env, conn):
    inst = add_inst(conn)
    add_rule(conn, inst, "1", T0 - timedelta(days=1))
    out = tasks.reconcile([{"institution": "KASI", "complete": False, "started_at": T0.isoformat()}, None])
    assert out["skipped"] == ["KASI", None] and rule(conn, "1")["missing_since"] is None
    out = tasks.reconcile([{"institution": "KASI", "complete": True, "started_at": T0.isoformat()}])
    json.dumps(out)
    assert out["institutions"]["KASI"]["missing"] == 1 and str(rule(conn, "1")["missing_since"]) == "2026-10-02"


def test_collect_institution_guards_inactive_and_returns_completeness(app_env, conn, monkeypatch):
    add_inst(conn, "ZZZ", "C9999", active=False)   # 설정 파일에 없는 시험 기관 (load_institutions가 덮지 않는다)
    seen = []

    def fake_sync(c, alio, blob, inst, limit=None):
        seen.append(inst["code"])
        return {"rules_seen": 0, "complete": True, "started_at": T0.isoformat()}

    monkeypatch.setattr(tasks, "sync_institution", fake_sync)
    with pytest.raises(ValueError, match="비활성 기관"):
        tasks.collect_institution("ZZZ")
    with pytest.raises(ValueError, match="ALIO 기관이 아님"):
        tasks.collect_institution("NOPE")
    r = tasks.collect_institution("ZZZ", include_inactive=True)
    assert seen == ["ZZZ"] and r["fetch_run_id"]   # M6-0: 수집 실행 이력(ops.fetch_run) id도 함께
    assert {k: v for k, v in r.items() if k != "fetch_run_id"} == {
        "institution": "ZZZ", "rules_seen": 0, "complete": True, "started_at": T0.isoformat()}


def test_backfill_runs_canary_collect_and_reconcile(app_env, conn, monkeypatch):
    calls = []
    monkeypatch.setattr(tasks, "canary_check", lambda: calls.append("canary") or {"ok": True})

    def fake_collect(code, *, include_inactive=False):
        calls.append((code, include_inactive))
        return {"institution": code, "complete": True, "started_at": T0.isoformat()}

    monkeypatch.setattr(tasks, "collect_institution", fake_collect)
    add_inst(conn, "ZZZ", "C9999", active=False)
    out = tasks.backfill("ZZZ")
    assert calls == ["canary", ("ZZZ", True)]
    assert out["reconcile"]["institutions"]["ZZZ"]["seen"] == 0
    json.dumps(out)
