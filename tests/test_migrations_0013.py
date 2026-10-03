"""0013: 검수 HOLD 상태와 사람 결정 보관(review_decision) — 재적재(TRUNCATE) 뒤 다시 만든 작업에 결정을 되살린다."""
import json

import pytest
from psycopg.errors import CheckViolation


def _task(conn, kind="REFERENCE", target="ref:w:a1:0:상법", detail=None):
    return conn.execute("INSERT INTO regulation.review_task (kind, target, detail) VALUES (%s, %s, %s)"
                        " ON CONFLICT (kind, target) DO UPDATE SET detail = EXCLUDED.detail RETURNING *",
                        (kind, target, json.dumps(detail or {"name": "상법"}))).fetchone()


def _decide(conn, kind, target, status, assignee=None, decision=None, detail=None):
    conn.execute("INSERT INTO regulation.review_decision (kind, target, status, assignee, decision, detail, resolved_at)"
                 " VALUES (%s, %s, %s, %s, %s, %s, CASE WHEN %s IN ('RESOLVED', 'DISMISSED') THEN now() END)",
                 (kind, target, status, assignee, json.dumps(decision) if decision else None,
                  json.dumps(detail) if detail else None, status))


def test_hold_status_allowed_and_unknown_rejected(conn):
    t = _task(conn)
    conn.execute("UPDATE regulation.review_task SET status = 'HOLD' WHERE id = %s", (t["id"],))
    with pytest.raises(CheckViolation):
        conn.execute("UPDATE regulation.review_task SET status = 'NOPE' WHERE id = %s", (t["id"],))


def test_regenerated_task_gets_human_decision_back(conn):
    _decide(conn, "REFERENCE", "ref:w:a1:0:상법", "DISMISSED", "김검수", {"action": "dismiss", "by": "김검수"})
    t = _task(conn)
    assert (t["status"], t["assignee"], t["decision"]["by"]) == ("DISMISSED", "김검수", "김검수")
    assert t["resolved_at"] is not None


def test_assignment_only_is_reapplied_and_status_stays_open(conn):
    _decide(conn, "REFERENCE", "ref:w:a1:0:상법", "OPEN", "이담당")
    t = _task(conn)
    assert (t["status"], t["assignee"], t["decision"]) == ("OPEN", "이담당", None)


def test_version_level_decision_needs_same_detail(conn):
    """PARSE·시행일 작업은 대상(버전 id)이 같아도 감지 내용이 바뀌면 새 문제다: 담당만 되살린다."""
    _decide(conn, "PARSE", "kr/reg/X/a@2020-01-01", "DISMISSED", "박", {"action": "dismiss"},
            detail={"check": "gap", "missing": [37]})
    t = _task(conn, "PARSE", "kr/reg/X/a@2020-01-01", {"check": "gap", "missing": [37, 40]})
    assert (t["status"], t["assignee"]) == ("OPEN", "박")
    conn.execute("DELETE FROM regulation.review_task")
    t = _task(conn, "PARSE", "kr/reg/X/a@2020-01-01", {"check": "gap", "missing": [37]})
    assert t["status"] == "DISMISSED"


def test_abolished_status_is_not_reapplied(conn):
    """폐지 판단의 원장은 alio_rule이다. 다시 후보가 되면 새 질문이다."""
    _decide(conn, "ABOLISHED", "work:w", "DISMISSED", "최", {"action": "dismiss"})
    t = _task(conn, "ABOLISHED", "work:w", {"seq": "1"})
    assert (t["status"], t["assignee"]) == ("OPEN", "최")


def test_decision_table_survives_structure_truncate(conn):
    from reg.core.ingest.process import STRUCTURE_TABLES

    _decide(conn, "REFERENCE", "ref:w:a1:0:상법", "RESOLVED", "김", {"action": "resolve"})
    conn.execute("TRUNCATE " + ", ".join(f"regulation.{t}" for t in STRUCTURE_TABLES) + " CASCADE")
    assert conn.execute("SELECT count(*) AS n FROM regulation.review_decision").fetchone()["n"] == 1
