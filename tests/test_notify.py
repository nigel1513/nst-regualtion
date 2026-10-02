from datetime import datetime

from reg.alerts.notify import build_notifications, import_owners, send_due


class FakeMailer:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def send(self, to, subject, body):
        if self.fail:
            raise OSError("smtp down")
        self.sent.append((to, subject, body))


def impact(conn, work="kr/reg/KASI/여비", path="a3", sev="HIGH", cause_path="a5"):
    conn.execute("INSERT INTO regulation.institution (code, name, kind) VALUES ('KASI','천문연','GRI') ON CONFLICT DO NOTHING")
    return conn.execute(
        "INSERT INTO ops.change_impact (cause_work_id, cause_version_id, cause_path, cause_change, affected_work_id,"
        " affected_path, rel_type, evidence, impact_kind, severity) VALUES ('kr/law/L1','kr/law/L1@2026-01-01',%s,"
        "'MODIFIED',%s,%s,'BASIS','「가상 연구법」 제5조에 따라','근거·위임·준용 대상 개정',%s) RETURNING id",
        (cause_path, work, path, sev)).fetchone()["id"]


def owner(conn, email, work="kr/reg/KASI/여비"):
    import_owners(conn, [{"work_id": work, "email": email, "name": "", "org_unit": "", "role": "OWNER"}])


def test_owner_then_admin_fallback_and_idempotent(conn):
    impact(conn)
    impact(conn, work="kr/reg/KASI/복무", path="a9", sev="MEDIUM")
    import_owners(conn, [{"work_id": "kr/reg/KASI/여비", "email": "owner@x", "name": "담당", "org_unit": "회계", "role": "OWNER"}])
    assert build_notifications(conn, {"KASI": ["admin@x"]}) == 2
    assert build_notifications(conn, {"KASI": ["admin@x"]}) == 0
    rec = sorted(r["recipient"] for r in conn.execute("SELECT recipient FROM ops.notification").fetchall())
    assert rec == ["admin@x", "owner@x"]


def test_high_immediately_others_once_a_day(conn):
    impact(conn)
    impact(conn, path="a4", sev="MEDIUM", cause_path="a6")
    owner(conn, "owner@x")
    build_notifications(conn, {})
    m = FakeMailer()
    st = send_due(conn, m, datetime(2026, 10, 2, 6, 0))
    assert st == {"emails": 1, "notifications": 1, "failed": 0} and "높음 1" in m.sent[0][1]
    assert send_due(conn, m, datetime(2026, 10, 2, 9, 0))["notifications"] == 1  # 하루 묶음
    impact(conn, path="a8", sev="LOW", cause_path="a6")
    build_notifications(conn, {})
    assert send_due(conn, m, datetime(2026, 10, 2, 15, 0))["notifications"] == 0  # 오늘 묶음은 이미 보냄
    assert send_due(conn, m, datetime(2026, 10, 3, 9, 0))["notifications"] == 1
    assert "a4" in m.sent[1][2] and "/alerts?id=" in m.sent[1][2]


def test_failure_is_recorded_and_retried(conn):
    impact(conn)
    owner(conn, "o@x")
    build_notifications(conn, {})
    assert send_due(conn, FakeMailer(fail=True), datetime(2026, 10, 2, 9, 0))["failed"] == 1
    d = conn.execute("SELECT status, attempts FROM ops.email_delivery").fetchone()
    assert (d["status"], d["attempts"]) == ("failed", 1)
    assert send_due(conn, FakeMailer(), datetime(2026, 10, 2, 9, 5))["notifications"] == 1


def test_closed_alerts_are_not_mailed(conn):
    iid = impact(conn)
    owner(conn, "o@x")
    build_notifications(conn, {})
    conn.execute("UPDATE ops.change_impact SET status = 'NO_ACTION' WHERE id = %s", (iid,))
    conn.commit()
    assert send_due(conn, FakeMailer(), datetime(2026, 10, 2, 9, 0))["notifications"] == 0
