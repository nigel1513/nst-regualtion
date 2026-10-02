"""reg alerts … · reg owners … — 개정 영향 분석·담당자 알림."""
import typer
import yaml

from reg.platform.db.conn import connect
from reg.platform.neo4j import neo4j_driver as _neo4j
from reg.platform.settings import ROOT, get_settings

alerts = typer.Typer(no_args_is_help=True, help="개정 영향 분석·담당자 알림")
owners = typer.Typer(no_args_is_help=True, help="규정별 담당자")


@alerts.command("scan")
def alerts_scan(no_sync: bool = typer.Option(False, "--no-sync", help="그래프 재투영 없이 스캔")) -> None:
    """그래프를 현행 기준으로 다시 투영한 뒤 대기 중인 개정 이벤트의 영향을 분석한다."""
    from reg.alerts.scan import scan_once
    from reg.graph.sync import graph_lock, sync_graph

    s = get_settings()
    conn = connect(s.database_url)
    with _neo4j(s) as drv, graph_lock(conn):
        if not no_sync:
            typer.echo(f"graph {sync_graph(conn, drv)}")
        total = {"claimed": 0, "ok": 0, "failed": 0, "impacts": 0}
        while (st := scan_once(conn, drv))["claimed"]:
            total = {k: total[k] + st[k] for k in total}
        typer.echo(f"scan {total}")


@alerts.command("notify")
def alerts_notify() -> None:
    """새 영향에 알림을 만들고, 보낼 때가 된 메일을 보낸다 (높음 즉시, 그 밖 매일 08시 이후 한 번)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from reg.alerts.notify import SmtpMailer, build_notifications, send_due

    s = get_settings()
    conn = connect(s.database_url)
    admins = yaml.safe_load((ROOT / "config/admins.yaml").read_text(encoding="utf-8")) or {}
    typer.echo(f"notifications +{build_notifications(conn, admins)}")
    now = datetime.now(ZoneInfo("Asia/Seoul")).replace(tzinfo=None)
    typer.echo(f"send {send_due(conn, SmtpMailer(s.smtp_host, s.smtp_port, s.smtp_from), now, web=s.web_url)}")




@owners.command("import")
def owners_import(path: str) -> None:
    """CSV(work_id,email,name,org_unit,role)로 담당자를 등록·갱신한다."""
    import csv

    from reg.alerts.notify import import_owners

    s = get_settings()
    conn = connect(s.database_url)
    with open(path, encoding="utf-8-sig", newline="") as f:
        typer.echo(f"owners {import_owners(conn, list(csv.DictReader(f)))}")


@alerts.command("backtest")
def alerts_backtest(limit: int = typer.Option(0, help="재생할 버전 수 (0이면 전체)")) -> None:
    """적재된 과거 개정을 재생해 영향 탐지를 사후 검증하고 보고서를 쓴다 (알림 없음)."""
    from datetime import datetime

    from reg.alerts.backtest import backtest
    from reg.graph.sync import graph_lock, sync_graph

    s = get_settings()
    conn = connect(s.database_url)
    with _neo4j(s) as drv, graph_lock(conn):
        g = sync_graph(conn, drv)
        r = backtest(conn, drv, limit or None)
    path = ROOT / f"docs/reports/{datetime.now():%Y-%m-%d}-impact-backtest.md"
    lines = [f"# 개정 영향 탐지 사후 검증 ({datetime.now():%Y-%m-%d %H:%M})", "",
             f"- 그래프: 규범문서 {g['works']} · 조항 {g['provisions']} · 참조 관계 {g['relations']}",
             f"- 재생한 개정 버전: {r['versions']} · 탐지한 영향: {r['impacts']} · 영향받은 규범문서: {r['works_affected']}",
             f"- 심각도: {r['by_severity']}", f"- 유형: {r['by_kind']}", "",
             "재생 결과는 RESOLVED(backtest)로 저장되어 알림이 나가지 않는다. 그래프는 현행 참조 기준이다.", "",
             "| 원인 | 조 | 변경 | 영향 규정 | 조 | 관계 | 심각도 |", "|---|---|---|---|---|---|---|"]
    lines += [f"| {e['cause_work_id']} | {e['cause_path']} | {e['cause_change']} | {e['affected_work_id']} |"
              f" {e['affected_path']} | {e['rel_type']} | {e['severity']} |" for e in r["examples"]]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    typer.echo(f"backtest {({k: v for k, v in r.items() if k != 'examples'})}\n보고서: {path}")
