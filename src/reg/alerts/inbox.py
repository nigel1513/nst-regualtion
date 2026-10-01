"""개정 알림함 조회·처리 (spec 9.2-6)."""
OPEN = ("NEW", "ACKED", "ACTION_REQUIRED")
DONE = ("NO_ACTION", "RESOLVED")
SELECT = ("SELECT ci.*, cw.title AS cause_title, aw.title AS affected_title, ai.code AS institution"
          " FROM regulation.change_impact ci LEFT JOIN regulation.work cw ON cw.id = ci.cause_work_id"
          " LEFT JOIN regulation.work aw ON aw.id = ci.affected_work_id"
          " LEFT JOIN regulation.institution ai ON ai.id = aw.institution_id")
ORDER = " ORDER BY CASE ci.severity WHEN 'HIGH' THEN 0 WHEN 'MEDIUM' THEN 1 ELSE 2 END, ci.created_at DESC, ci.id"


def list_alerts(conn, status: str = "open", institution: str | None = None, severity: str | None = None,
                limit: int = 200) -> list[dict]:
    statuses = OPEN if status == "open" else DONE if status == "done" else (status,)
    q, args = SELECT + " WHERE ci.status = ANY(%s)", [list(statuses)]
    if institution:
        q += " AND (ai.code = %s OR ci.affected_work_id LIKE %s)"
        args += [institution, f"kr/reg/{institution}/%"]
    if severity:
        q += " AND ci.severity = %s"
        args.append(severity)
    return conn.execute(q + ORDER + " LIMIT %s", (*args, limit)).fetchall()


def _text(conn, pv_id: int | None) -> str | None:
    if pv_id is None:
        return None
    r = conn.execute("SELECT number_label, text FROM regulation.provision_version WHERE id = %s", (pv_id,)).fetchone()
    return f"{r['number_label']} {r['text']}".strip() if r else None


def alert_detail(conn, impact_id: int) -> dict | None:
    row = conn.execute(SELECT + " WHERE ci.id = %s", (impact_id,)).fetchone()
    if row is None:
        return None
    ch = conn.execute(
        "SELECT c.from_pv_id, c.to_pv_id FROM regulation.provision_change c"
        " LEFT JOIN regulation.provision_version t ON t.id = c.to_pv_id"
        " LEFT JOIN regulation.provision_version f ON f.id = c.from_pv_id"
        " WHERE c.to_version_id = %s AND (t.path = %s OR f.path = %s) LIMIT 1",
        (row["cause_version_id"], row["cause_path"], row["cause_path"])).fetchone()
    aff = conn.execute(
        "SELECT pv.id FROM regulation.version_provision vp JOIN regulation.provision_version pv"
        " ON pv.id = vp.provision_version_id WHERE vp.work_version_id = %s AND pv.path = %s",
        (row["affected_version_id"], row["affected_path"])).fetchone() if row["affected_version_id"] else None
    rec = [r["who"] for r in conn.execute(  # 알림을 받은 사람과 지금 등록된 담당자
        "SELECT recipient AS who FROM regulation.notification WHERE impact_id = %s"
        " UNION SELECT email FROM regulation.owner_assignment WHERE work_id = %s ORDER BY 1",
        (impact_id, row["affected_work_id"])).fetchall()]
    return {**row, "cause_old": _text(conn, ch and ch["from_pv_id"]), "cause_new": _text(conn, ch and ch["to_pv_id"]),
            "affected_text": _text(conn, aff and aff["id"]), "recipients": rec}


def set_status(conn, impact_id: int, status: str, note: str | None) -> bool:
    n = conn.execute("UPDATE regulation.change_impact SET status = %s, resolution_note = coalesce(%s, resolution_note),"
                     " updated_at = now() WHERE id = %s", (status, note, impact_id)).rowcount
    conn.commit()
    return bool(n)
