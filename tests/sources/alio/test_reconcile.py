import json
from datetime import timedelta

import pytest

from reg.sources.alio.reconcile import AbolishError, decide, project, run_reconcile
from tests.sources.alio.seed import T0, add_inst, add_rule, rule, see, task, work

YESTERDAY = T0 - timedelta(days=1)


def run_day(conn, n: int, seen: list[str], code: str = "KASI") -> dict:
    """n일차 배치: started_at = T0 + n일, seen 규정은 실행 중에 본 것으로 한다."""
    started = T0 + timedelta(days=n)
    for s in seen:
        see(conn, s, started + timedelta(minutes=1))
    return run_reconcile(conn, [{"institution": code, "complete": True, "started_at": started.isoformat()}])


def candidate(conn):
    """규정 1은 사라지고 규정 2는 매일 보이는 기관, 3일째에 1이 폐지 후보."""
    inst = add_inst(conn)
    gone = add_rule(conn, inst, "1", YESTERDAY)
    add_rule(conn, inst, "2", YESTERDAY)
    for n in range(3):
        run_day(conn, n, ["2"])
    return inst, gone


def test_missing_three_days_becomes_candidate_with_task(conn):
    inst = add_inst(conn)
    gone = add_rule(conn, inst, "1", YESTERDAY)
    add_rule(conn, inst, "2", YESTERDAY)
    run_day(conn, 0, ["2"])
    assert str(rule(conn, "1")["missing_since"]) == "2026-10-02" and rule(conn, "2")["missing_since"] is None
    run_day(conn, 1, ["2"])
    assert work(conn, gone)["status"] == "ACTIVE" and str(rule(conn, "1")["missing_since"]) == "2026-10-02"
    out = run_day(conn, 2, ["2"])
    assert out["institutions"]["KASI"]["candidates"] == 1
    assert work(conn, gone)["status"] == "ABOLISHED_CANDIDATE" and rule(conn, "1")["abolish_state"] == "CANDIDATE"
    t = task(conn, gone)
    assert t["status"] == "OPEN"
    assert t["detail"] == {"seq": "1", "title": "규정1", "institution": "KASI", "missing_since": "2026-10-02"}
    json.dumps(out)   # Airflow XCom


def test_incomplete_result_marks_nothing(conn):
    inst = add_inst(conn)
    add_rule(conn, inst, "1", YESTERDAY)
    out = run_reconcile(conn, [{"institution": "KASI", "complete": False, "started_at": T0.isoformat()}, None])
    assert out["skipped"] == ["KASI", None] and rule(conn, "1")["missing_since"] is None


def test_reappearing_candidate_returns_to_active_and_dismisses_task(conn):
    _, gone = candidate(conn)
    out = run_day(conn, 3, ["1", "2"])
    assert out["institutions"]["KASI"]["reappeared"] == 1
    assert work(conn, gone)["status"] == "ACTIVE"
    r = rule(conn, "1")
    assert r["missing_since"] is None and r["abolish_state"] is None
    t = task(conn, gone)
    assert t["status"] == "DISMISSED" and t["decision"] == {"auto": "not_candidate"}


def test_confirm_sets_abolished_on_to_missing_since_and_survives_next_day(conn):
    _, gone = candidate(conn)
    r = decide(conn, gone, confirm=True)
    assert r["status"] == "ABOLISHED" and str(r["abolished_on"]) == "2026-10-02"
    assert task(conn, gone)["status"] == "RESOLVED" and task(conn, gone)["decision"] == {"confirm": True}
    run_day(conn, 3, ["2"])
    assert work(conn, gone)["status"] == "ABOLISHED" and task(conn, gone)["status"] == "RESOLVED"


def test_confirmed_abolition_reverts_when_rule_reappears(conn):
    _, gone = candidate(conn)
    decide(conn, gone, confirm=True)
    run_day(conn, 4, ["1", "2"])
    assert work(conn, gone) == {"status": "ACTIVE", "abolished_on": None}
    assert rule(conn, "1")["abolished_on"] is None


def test_reject_then_still_missing_reopens_task(conn):
    _, gone = candidate(conn)
    r = decide(conn, gone, confirm=False)
    assert r["status"] == "ACTIVE" and rule(conn, "1")["missing_since"] is None
    assert task(conn, gone)["status"] == "DISMISSED" and task(conn, gone)["decision"] == {"confirm": False}
    for n in (3, 4):
        run_day(conn, n, ["2"])
        assert work(conn, gone)["status"] == "ACTIVE"
    assert str(rule(conn, "1")["missing_since"]) == "2026-10-05"
    run_day(conn, 5, ["2"])
    assert work(conn, gone)["status"] == "ABOLISHED_CANDIDATE"
    t = task(conn, gone)
    assert t["status"] == "OPEN" and t["decision"] is None and t["detail"]["missing_since"] == "2026-10-05"


def test_decide_rejects_invalid_states(conn):
    inst = add_inst(conn)
    wid = add_rule(conn, inst, "1", YESTERDAY)
    with pytest.raises(AbolishError, match="폐지 후보가 아닙니다"):
        decide(conn, wid, confirm=True)
    with pytest.raises(AbolishError, match="폐지 후보·폐지 상태가 아닙니다"):
        decide(conn, wid, confirm=False)
    conn.execute("INSERT INTO regulation.work (id, kind, title) VALUES ('kr/law/001', '법률', '법')")
    conn.commit()
    with pytest.raises(AbolishError, match="ALIO 내부규정이 아닙니다"):
        decide(conn, "kr/law/001", confirm=True)
    with pytest.raises(AbolishError, match="ALIO 내부규정이 아닙니다"):
        decide(conn, "kr/reg/없음", confirm=True)


def test_rerun_same_day_is_idempotent(conn):
    _, gone = candidate(conn)
    again = run_day(conn, 2, ["2"])
    assert again["projection"] == {"status_changed": 0, "tasks_opened": 0, "tasks_dismissed": 0}
    assert str(rule(conn, "1")["missing_since"]) == "2026-10-02"
    assert conn.execute("SELECT count(*) AS n FROM regulation.review_task WHERE kind = 'ABOLISHED'").fetchone()["n"] == 1


def test_shrink_guard_skips_marking(conn):
    inst = add_inst(conn)
    for i in range(12):
        add_rule(conn, inst, str(i), YESTERDAY)
    out = run_day(conn, 0, ["0", "1", "2", "3"])
    st = out["institutions"]["KASI"]
    assert st["seen"] == 4 and st["known"] == 12 and st["missing"] == 0 and "목록 급감" in st["guard"]
    assert conn.execute("SELECT count(*) AS n FROM regulation.alio_rule WHERE missing_since IS NOT NULL").fetchone()["n"] == 0


def test_shrink_guard_on_empty_list(conn):
    """기관명이 바뀌어 검색 결과가 0건인 날: 전체가 사라진 것으로 기록하지 않는다."""
    inst = add_inst(conn)
    for i in range(10):
        add_rule(conn, inst, str(i), YESTERDAY)
    st = run_day(conn, 0, [])["institutions"]["KASI"]
    assert st["seen"] == 0 and st["missing"] == 0 and st["guard"]


def test_projection_restores_after_rebuild(conn):
    inst, gone = candidate(conn)
    kept = add_rule(conn, inst, "3", YESTERDAY)
    conn.execute("UPDATE regulation.alio_rule SET missing_since = '2026-09-01', abolish_state = 'ABOLISHED',"
                 " abolished_on = '2026-09-01' WHERE seq = '3'")
    project(conn)
    conn.commit()
    # reg process --rebuild 흉내: work가 기본값으로 다시 만들어지고 검수 작업은 비워진다
    conn.execute("UPDATE regulation.work SET status = 'ACTIVE', abolished_on = NULL")
    conn.execute("DELETE FROM regulation.review_task")
    conn.commit()
    p = project(conn)
    conn.commit()
    assert p["status_changed"] == 2 and p["tasks_opened"] == 1
    assert work(conn, gone)["status"] == "ABOLISHED_CANDIDATE" and task(conn, gone)["status"] == "OPEN"
    assert work(conn, kept) == {"status": "ABOLISHED", "abolished_on": T0.date().replace(month=9, day=1)}


def test_rule_without_work_is_never_candidate(conn):
    inst = add_inst(conn)
    add_rule(conn, inst, "1", YESTERDAY, work=False)
    for n in range(4):
        run_day(conn, n, [])
    r = rule(conn, "1")
    assert str(r["missing_since"]) == "2026-10-02" and r["abolish_state"] is None


def test_law_work_status_is_not_touched(conn):
    conn.execute("INSERT INTO regulation.work (id, kind, title, status) VALUES ('kr/law/9', '법률', '법', 'ABOLISHED')")
    conn.commit()
    project(conn)
    conn.commit()
    assert work(conn, "kr/law/9")["status"] == "ABOLISHED"
