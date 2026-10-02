"""개정 알림함 조회·처리 (spec 9.2-6)."""
OPEN = ("NEW", "ACKED", "ACTION_REQUIRED")
DONE = ("NO_ACTION", "RESOLVED")
SELECT = ("SELECT ci.*, cw.title AS cause_title, aw.title AS affected_title, ai.code AS institution"
          " FROM ops.change_impact ci LEFT JOIN regulation.work cw ON cw.id = ci.cause_work_id"
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
    # 원인 경로는 참조가 가리키는 단위(예: a5)이고 실제 변경은 그 아래(a5.p1)일 수 있다. 전체 참조면 'a3, a5' 목록이다
    paths = [p.strip() for p in row["cause_path"].split(" 외 ")[0].split(",")]
    chs = conn.execute(
        "SELECT DISTINCT ON (coalesce(t.path, f.path)) c.from_pv_id, c.to_pv_id, coalesce(t.path, f.path) AS path"
        " FROM regulation.provision_change c"
        " LEFT JOIN regulation.provision_version t ON t.id = c.to_pv_id"
        " LEFT JOIN regulation.provision_version f ON f.id = c.from_pv_id"
        " WHERE c.to_version_id = %s AND c.kind <> 'ANNOTATION_ONLY'"
        " AND EXISTS (SELECT 1 FROM unnest(%s::text[]) p WHERE coalesce(t.path, f.path) = p"
        "  OR coalesce(t.path, f.path) LIKE p || '.%%' OR f.path = p OR f.path LIKE p || '.%%')"
        " ORDER BY coalesce(t.path, f.path) LIMIT 12", (row["cause_version_id"], paths)).fetchall()

    def joined(key: str) -> str | None:
        texts = [t for c in chs if (t := _text(conn, c[key]))]
        return "\n".join(texts) or None

    aff = conn.execute(
        "SELECT pv.id FROM regulation.version_provision vp JOIN regulation.provision_version pv"
        " ON pv.id = vp.provision_version_id WHERE vp.work_version_id = %s AND pv.path = %s",
        (row["affected_version_id"], row["affected_path"])).fetchone() if row["affected_version_id"] else None
    rec = [r["who"] for r in conn.execute(  # 알림을 받은 사람과 지금 등록된 담당자
        "SELECT recipient AS who FROM ops.notification WHERE impact_id = %s"
        " UNION SELECT email FROM ops.owner_assignment WHERE work_id = %s ORDER BY 1",
        (impact_id, row["affected_work_id"])).fetchall()]
    return {**row, "cause_old": joined("from_pv_id"), "cause_new": joined("to_pv_id"),
            "affected_text": _text(conn, aff and aff["id"]), "recipients": rec}


def set_status(conn, impact_id: int, status: str, note: str | None) -> bool:
    n = conn.execute("UPDATE ops.change_impact SET status = %s, resolution_note = coalesce(%s, resolution_note),"
                     " updated_at = now() WHERE id = %s", (status, note, impact_id)).rowcount
    conn.commit()
    return bool(n)
