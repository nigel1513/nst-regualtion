"""폐지 감지 (spec 3.3).

alio_rule이 폐지 상태의 원장이다: missing_since(처음 사라진 날), abolish_state(NULL|CANDIDATE|ABOLISHED), abolished_on.
regulation.work.status·abolished_on과 ABOLISHED 검수 작업은 원장에서 다시 만드는 투영(project)이다.
그래서 `reg process --rebuild`가 work·review_task를 비워도 project() 한 번으로 복구된다.
"""
import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
CANDIDATE_AFTER_DAYS = 2   # 처음 사라진 날을 포함해 연속 3일째(missing_since <= 오늘-2)에 폐지 후보
SHRINK_MIN_KNOWN = 10      # 목록 급감 보호: 알려진 규정이 이만큼 이상이고
SHRINK_RATIO = 0.5         # 이번에 본 규정이 그 비율 미만이면 그날은 사라짐을 기록하지 않는다
STATE_NAME = {None: "현행", "CANDIDATE": "폐지 후보", "ABOLISHED": "폐지"}

_DESIRED = """
SELECT w.id AS work_id, r.seq, r.title, r.missing_since, i.code AS institution,
  CASE r.abolish_state WHEN 'ABOLISHED' THEN 'ABOLISHED' WHEN 'CANDIDATE' THEN 'ABOLISHED_CANDIDATE'
       ELSE 'ACTIVE' END AS status,
  CASE WHEN r.abolish_state = 'ABOLISHED' THEN r.abolished_on END AS abolished_on
FROM regulation.alio_rule r
JOIN regulation.work w ON w.external_ids ? 'alio_seq' AND w.external_ids->>'alio_seq' = r.seq
JOIN regulation.institution i ON i.id = r.institution_id
"""


class AbolishError(Exception):
    """폐지 확정·반려를 할 수 없는 상태."""


def mark_missing(conn, institution_id: int, started_at: datetime, today: date) -> dict:
    """완결된 수집 한 번의 결과를 원장에 반영한다. 커밋하지 않는다."""
    back = conn.execute(
        "UPDATE regulation.alio_rule SET missing_since = NULL, abolish_state = NULL, abolished_on = NULL"
        " WHERE institution_id = %s AND last_seen_at >= %s"
        " AND (missing_since IS NOT NULL OR abolish_state IS NOT NULL) RETURNING seq",
        (institution_id, started_at)).fetchall()
    n = conn.execute(
        "SELECT count(*) FILTER (WHERE last_seen_at >= %s) AS seen,"
        " count(*) FILTER (WHERE abolish_state IS DISTINCT FROM 'ABOLISHED') AS known"
        " FROM regulation.alio_rule WHERE institution_id = %s", (started_at, institution_id)).fetchone()
    out = {"seen": n["seen"], "known": n["known"], "reappeared": len(back), "missing": 0, "candidates": 0,
           "guard": None}
    if n["known"] >= SHRINK_MIN_KNOWN and n["seen"] < n["known"] * SHRINK_RATIO:
        out["guard"] = f"목록 급감: 이번 {n['seen']}건 / 알려진 {n['known']}건 — 사라짐 기록 생략"
        return out
    out["missing"] = conn.execute(
        "UPDATE regulation.alio_rule SET missing_since = coalesce(missing_since, %s)"
        " WHERE institution_id = %s AND last_seen_at < %s", (today, institution_id, started_at)).rowcount
    out["candidates"] = conn.execute(
        "UPDATE regulation.alio_rule r SET abolish_state = 'CANDIDATE'"
        " WHERE r.institution_id = %s AND r.abolish_state IS NULL AND r.missing_since <= %s"
        " AND EXISTS (SELECT 1 FROM regulation.work w WHERE w.external_ids ? 'alio_seq' AND w.external_ids->>'alio_seq' = r.seq)",
        (institution_id, today - timedelta(days=CANDIDATE_AFTER_DAYS))).rowcount
    return out


def project(conn) -> dict:
    """원장 → work.status·abolished_on, ABOLISHED 검수 작업. ALIO 규정이 아닌 work는 건드리지 않는다. 커밋하지 않는다."""
    changed = conn.execute(
        "UPDATE regulation.work w SET status = d.status, abolished_on = d.abolished_on"
        f" FROM ({_DESIRED}) d WHERE w.id = d.work_id"
        " AND (w.status, w.abolished_on) IS DISTINCT FROM (d.status, d.abolished_on)").rowcount
    opened = conn.execute(
        "INSERT INTO regulation.review_task (kind, target, work_id, detail)"
        " SELECT 'ABOLISHED', 'work:' || d.work_id, d.work_id, jsonb_build_object('seq', d.seq, 'title', d.title,"
        "  'institution', d.institution, 'missing_since', d.missing_since)"
        f" FROM ({_DESIRED}) d WHERE d.status = 'ABOLISHED_CANDIDATE'"
        " ON CONFLICT (kind, target) DO UPDATE SET detail = EXCLUDED.detail, status = 'OPEN',"
        "  resolved_at = NULL, decision = NULL"
        " WHERE NOT (regulation.review_task.status IN ('OPEN', 'HOLD')"  # 보류는 내용이 같으면 그대로 둔다
        "  AND regulation.review_task.detail = EXCLUDED.detail)").rowcount
    dismissed = conn.execute(
        "UPDATE regulation.review_task t SET status = 'DISMISSED', resolved_at = now(),"
        " decision = '{\"auto\": \"not_candidate\"}'::jsonb"
        f" WHERE t.kind = 'ABOLISHED' AND t.status IN ('OPEN', 'HOLD') AND NOT EXISTS (SELECT 1 FROM ({_DESIRED}) d"
        "  WHERE 'work:' || d.work_id = t.target AND d.status = 'ABOLISHED_CANDIDATE')").rowcount
    return {"status_changed": changed, "tasks_opened": opened, "tasks_dismissed": dismissed}


def decide(conn, work_id: str, confirm: bool) -> dict:
    """사람의 판단: confirm=True면 폐지 확정(폐지일 = 처음 사라진 날), False면 반려(현행, missing_since 초기화). 커밋한다."""
    r = conn.execute(
        "SELECT r.seq, r.abolish_state FROM regulation.work w"
        " JOIN regulation.alio_rule r ON r.seq = w.external_ids->>'alio_seq' WHERE w.id = %s FOR UPDATE OF r",
        (work_id,)).fetchone()
    if r is None:
        conn.rollback()
        raise AbolishError(f"ALIO 내부규정이 아닙니다: {work_id}")
    target = f"work:{work_id}"
    if confirm:
        if r["abolish_state"] != "CANDIDATE":
            conn.rollback()
            raise AbolishError(f"폐지 후보가 아닙니다 (현재 {STATE_NAME[r['abolish_state']]}): {work_id}")
        conn.execute("UPDATE regulation.alio_rule SET abolish_state = 'ABOLISHED', abolished_on = missing_since"
                     " WHERE seq = %s", (r["seq"],))
        conn.execute("UPDATE regulation.review_task SET status = 'RESOLVED', resolved_at = now(), decision = %s"
                     " WHERE kind = 'ABOLISHED' AND target = %s", (json.dumps({"confirm": True}), target))
    else:
        if r["abolish_state"] is None:
            conn.rollback()
            raise AbolishError(f"폐지 후보·폐지 상태가 아닙니다: {work_id}")
        conn.execute("UPDATE regulation.alio_rule SET abolish_state = NULL, abolished_on = NULL, missing_since = NULL"
                     " WHERE seq = %s", (r["seq"],))
        conn.execute("UPDATE regulation.review_task SET status = 'DISMISSED', resolved_at = now(), decision = %s"
                     " WHERE kind = 'ABOLISHED' AND target = %s", (json.dumps({"confirm": False}), target))
    project(conn)
    conn.commit()
    return conn.execute("SELECT id AS work_id, status, abolished_on FROM regulation.work WHERE id = %s",
                        (work_id,)).fetchone()


def run_reconcile(conn, results: list[dict | None]) -> dict:
    """기관별 수집 결과(collect_institution 반환값) 중 완결된 것만 대조한 뒤 전체를 투영한다. 커밋한다.

    results=[]이면 투영만 한다(rebuild 뒤 복구용 `reg alio reconcile`)."""
    out: dict = {"institutions": {}, "skipped": []}
    for r in results:
        code = r.get("institution") if isinstance(r, dict) else None
        if not isinstance(r, dict) or not r.get("complete"):
            out["skipped"].append(code)
            continue
        inst = conn.execute("SELECT id FROM regulation.institution WHERE code = %s", (code,)).fetchone()
        if inst is None:
            out["skipped"].append(code)
            continue
        started = datetime.fromisoformat(r["started_at"])
        out["institutions"][code] = mark_missing(conn, inst["id"], started, started.astimezone(KST).date())
    out["projection"] = project(conn)
    conn.commit()
    return out
