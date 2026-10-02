"""담당자 알림 (spec 9.2-5): 담당자 → 없으면 기관 관리자. 높음은 즉시, 그 밖은 하루 한 번 묶어 보낸다."""
import smtplib
from collections import defaultdict
from datetime import datetime
from email.message import EmailMessage

SEV_KO = {"HIGH": "높음", "MEDIUM": "중간", "LOW": "낮음"}
URGENT, DAILY = "[규정 개정 알림·긴급]", "[규정 개정 알림·일일]"


class SmtpMailer:
    def __init__(self, host: str, port: int, sender: str):
        self.host, self.port, self.sender = host, port, sender

    def send(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.sender, to, subject
        msg.set_content(body, charset="utf-8")
        with smtplib.SMTP(self.host, self.port, timeout=10) as s:
            s.send_message(msg)


def import_owners(conn, rows: list[dict]) -> int:
    for r in rows:
        conn.execute("INSERT INTO ops.owner_assignment (work_id, email, name, org_unit, role)"
                     " VALUES (%(work_id)s, %(email)s, %(name)s, %(org_unit)s, %(role)s)"
                     " ON CONFLICT (work_id, email) DO UPDATE SET name = EXCLUDED.name, org_unit = EXCLUDED.org_unit,"
                     " role = EXCLUDED.role", {**r, "role": r.get("role") or "OWNER"})
    conn.commit()
    return len(rows)


def _inst_code(imp: dict) -> str | None:
    if imp["code"]:
        return imp["code"]
    parts = imp["affected_work_id"].split("/")
    return parts[2] if len(parts) > 2 and parts[1] == "reg" else None


def build_notifications(conn, admins: dict[str, list[str]]) -> int:
    """새 영향마다 수신자를 정해 알림을 만든다. 같은 (영향, 수신자)는 한 번만."""
    n = 0
    for imp in conn.execute(
            "SELECT ci.id, ci.affected_work_id, ci.severity, i.code FROM ops.change_impact ci"
            " LEFT JOIN regulation.work w ON w.id = ci.affected_work_id"
            " LEFT JOIN regulation.institution i ON i.id = w.institution_id WHERE ci.status = 'NEW'").fetchall():
        owners = [r["email"] for r in conn.execute("SELECT email FROM ops.owner_assignment WHERE work_id = %s"
                                                   " ORDER BY role, email", (imp["affected_work_id"],)).fetchall()]
        for to in owners or admins.get(_inst_code(imp) or "", []):
            n += conn.execute("INSERT INTO ops.notification (impact_id, recipient, severity) VALUES (%s,%s,%s)"
                              " ON CONFLICT DO NOTHING", (imp["id"], to, imp["severity"])).rowcount
    conn.commit()
    return n


def _body(rows: list[dict], web: str) -> str:
    lines = ["규정·법령 개정으로 검토가 필요한 조항이 있습니다.", ""]
    for r in rows:
        lines += [f"- [{SEV_KO[r['severity']]}] {r['impact_kind']}",
                  f"  원인: {r['cause_work_id']} {r['cause_path']} ({r['cause_change']})",
                  f"  영향: {r['affected_work_id']} {r['affected_path']} — {r['rel_type']}",
                  f"  근거 문구: {r['evidence'] or '-'}", f"  알림함: {web}/alerts?id={r['impact_id']}", ""]
    lines.append("이 메일은 NST 규정·법령 플랫폼이 자동으로 보냈습니다. 법적 판단이 아니며 소관부서 검토가 필요합니다.")
    return "\n".join(lines)


def _daily_sent(conn, to: str, now: datetime) -> bool:
    return conn.execute("SELECT 1 FROM ops.email_delivery WHERE recipient = %s AND status = 'sent'"
                        " AND subject LIKE %s AND sent_at::date = %s", (to, DAILY + "%", now.date())).fetchone() is not None


def send_due(conn, mailer, now: datetime, digest_hour: int = 8, web: str = "http://192.168.0.3:21060") -> dict:
    st = {"emails": 0, "notifications": 0, "failed": 0}
    rows = conn.execute(
        "SELECT n.id, n.recipient, n.severity, n.impact_id, ci.cause_work_id, ci.cause_path, ci.cause_change,"
        " ci.affected_work_id, ci.affected_path, ci.rel_type, ci.evidence, ci.impact_kind"
        " FROM ops.notification n JOIN ops.change_impact ci ON ci.id = n.impact_id"
        " WHERE n.sent_at IS NULL AND ci.status IN ('NEW', 'ACKED', 'ACTION_REQUIRED') ORDER BY n.id").fetchall()
    batches: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        batches[(r["recipient"], URGENT if r["severity"] == "HIGH" else DAILY)].append(r)
    for (to, kind), items in batches.items():
        if kind == DAILY and (now.hour < digest_hour or _daily_sent(conn, to, now)):
            continue
        high = sum(1 for r in items if r["severity"] == "HIGH")
        subject = f"{kind} 영향 {len(items)}건 (높음 {high})"
        body = _body(items, web)
        ids = [r["id"] for r in items]
        d = conn.execute("INSERT INTO ops.email_delivery (recipient, subject, body, notification_ids)"
                         " VALUES (%s,%s,%s,%s) RETURNING id", (to, subject, body, ids)).fetchone()["id"]
        try:
            mailer.send(to, subject, body)
            conn.execute("UPDATE ops.email_delivery SET status = 'sent', attempts = attempts + 1, sent_at = %s"
                         " WHERE id = %s", (now, d))
            conn.execute("UPDATE ops.notification SET sent_at = %s WHERE id = ANY(%s)", (now, ids))
            st["emails"] += 1
            st["notifications"] += len(ids)
        except Exception as e:  # 발송 실패는 기록만 하고 다음 실행에서 다시 보낸다
            conn.execute("UPDATE ops.email_delivery SET status = 'failed', attempts = attempts + 1,"
                         " last_error = %s WHERE id = %s", (f"{type(e).__name__}: {e}"[:500], d))
            st["failed"] += 1
        conn.commit()
    return st
