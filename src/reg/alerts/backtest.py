"""사후 검증 (spec 12): 이미 적재된 개정(각 규범문서의 두 번째 이후 버전)을 다시 흘려 영향 탐지를 재생한다.

재생 결과는 알림 대상이 아니므로 RESOLVED(backtest)로 둔다. 그래프는 현행 기준이라 과거 시점의 참조와 다를 수 있다."""
from collections import Counter

from reg.alerts.impact import analyze_version


def backtest(conn, driver, limit: int | None = None) -> dict:
    versions = conn.execute(
        "SELECT v.work_id, v.id FROM regulation.work_version v WHERE v.effective_from IS NOT NULL AND EXISTS ("
        " SELECT 1 FROM regulation.work_version o WHERE o.work_id = v.work_id AND o.effective_from < v.effective_from)"
        # 알림을 기다리는 실제 개정은 재생하지 않는다 (재생 결과가 유일 키를 먼저 차지해 알림이 묻히지 않게)
        " AND NOT EXISTS (SELECT 1 FROM regulation.outbox e WHERE e.topic = 'regulation.version_loaded'"
        " AND e.processed_at IS NULL AND e.payload->>'version_id' = v.id)"
        " ORDER BY v.effective_from, v.id" + (" LIMIT %s" % int(limit) if limit else "")).fetchall()
    rows = []
    for v in versions:
        rows += analyze_version(conn, driver, v["work_id"], v["id"], status="RESOLVED", note="backtest")
    return {"versions": len(versions), "impacts": len(rows),
            "by_severity": dict(Counter(r["severity"] for r in rows)),
            "by_kind": dict(Counter(r["impact_kind"] for r in rows)),
            "works_affected": len({r["affected_work_id"] for r in rows}),
            "examples": [{k: r[k] for k in ("cause_work_id", "cause_path", "cause_change", "affected_work_id",
                                            "affected_path", "rel_type", "severity")} for r in rows[:15]]}
