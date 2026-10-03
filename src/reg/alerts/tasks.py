"""Airflow·CLI 진입점 (overview §2.6)."""
from reg.platform.runs import open_conn, task_run


def scan() -> dict:
    """대기 중인 개정 이벤트의 영향 분석 (그래프는 graph.tasks.sync가 먼저 증분 반영)."""
    from reg.alerts.scan import scan_once
    from reg.graph.sync import graph_lock
    from reg.platform.neo4j import neo4j_driver

    with open_conn() as conn, task_run("alerts.scan", conn) as st, neo4j_driver() as drv, graph_lock(conn):
        total = {"claimed": 0, "ok": 0, "failed": 0, "impacts": 0}
        while (r := scan_once(conn, drv))["claimed"]:
            total = {k: total[k] + r[k] for k in total}
        st.update(total)
        return dict(st)


def notify() -> dict:
    """새 영향에 알림을 만들고 보낼 때가 된 메일을 보낸다."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import yaml

    from reg.alerts.notify import SmtpMailer, build_notifications, send_due
    from reg.platform.settings import ROOT, get_settings

    s = get_settings()
    admins = yaml.safe_load((ROOT / "config/admins.yaml").read_text(encoding="utf-8")) or {}
    with open_conn() as conn, task_run("alerts.notify", conn) as st:
        st["notifications"] = build_notifications(conn, admins)
        now = datetime.now(ZoneInfo("Asia/Seoul")).replace(tzinfo=None)
        st["send"] = send_due(conn, SmtpMailer(s.smtp_host, s.smtp_port, s.smtp_from), now, web=s.web_url)
        return dict(st)
