"""개정 이벤트 소비 → 영향 분석. 질의응답과 독립된 경로다 (spec 9)."""
from reg.alerts.impact import analyze_version

TOPIC = "regulation.version_loaded"
MAX_ATTEMPTS = 3


def scan_once(conn, driver, limit: int = 100) -> dict:
    """대기 중인 version_loaded 이벤트마다 영향 분석. 실패(그래프 장애 등)는 처리 완료로 두지 않고 다음 실행에서 다시 한다."""
    st = {"claimed": 0, "ok": 0, "failed": 0, "impacts": 0}
    tried: list[int] = []
    while st["claimed"] < limit:
        ev = conn.execute("SELECT id, payload FROM regulation.outbox WHERE topic = %s AND processed_at IS NULL"
                          " AND attempts < %s AND NOT (id = ANY(%s)) ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED",
                          (TOPIC, MAX_ATTEMPTS, tried)).fetchone()
        if ev is None:
            break
        tried.append(ev["id"])
        st["claimed"] += 1
        try:
            rows = analyze_version(conn, driver, ev["payload"]["work_id"], ev["payload"]["version_id"])
            conn.execute("UPDATE regulation.outbox SET processed_at = now(), claimed_at = now(), last_error = NULL"
                         " WHERE id = %s", (ev["id"],))
            st["ok"] += 1
            st["impacts"] += len(rows)
        except Exception as e:
            conn.rollback()
            conn.execute("UPDATE regulation.outbox SET attempts = attempts + 1, claimed_at = now(), last_error = %s"
                         " WHERE id = %s", (f"{type(e).__name__}: {e}"[:2000], ev["id"]))
            st["failed"] += 1
        conn.commit()
    return st
