"""reg law … — law.go.kr 법령 미러 (sources/lawgo). Airflow는 같은 일을 tasks.py로 부른다."""
import json

import typer

law = typer.Typer(no_args_is_help=True, help="law.go.kr 법령 미러")


def _echo(fn, *args) -> None:
    from reg.sources.lawgo.errors import LawGoError

    try:
        st = fn(*args)
    except LawGoError as e:
        typer.echo(f"실패: {e}", err=True)
        raise typer.Exit(1) from e
    typer.echo(json.dumps(st, ensure_ascii=False, indent=2, default=str))


@law.command("sync")
def sync_cmd(day: str = typer.Option(None, "--date", help="이 날짜(YYYY-MM-DD)를 마지막 성공일로 보고 다시 훑는다")) -> None:
    """일 변경분: 최신순 목록 → 새 판본 본문·별표 (DAG reg_law_daily와 같다)."""
    from reg.sources.lawgo import tasks

    _echo(tasks.sync_daily, day)


@law.command("full")
def full_cmd() -> None:
    """전체 대조: 누락 보충·폐지·행정규칙 카탈로그·별표 목록. 최초 적재도 이것으로 한다."""
    from reg.sources.lawgo import tasks

    _echo(tasks.sync_full)


def targets_report(conn, cfg, top: int | None = None) -> dict:
    """법령 미러 대상 목록과 사유·인용 수 (읽기만 한다)."""
    from reg.sources.lawgo.scope import law_plan

    p = law_plan(conn, cfg)
    mirrored = {r["n"] for r in conn.execute(
        "SELECT name_norm AS n FROM law.law_master WHERE family = 'law' AND status = '현행'").fetchall()}

    def one(t) -> dict:
        return {"name": t.name, "reasons": t.reasons, "citations": t.citations, "parent": t.parent,
                "mirrored": t.norm in mirrored}
    cited = [t for t in p.targets if "cited" in t.reasons]
    return {"counts": p.counts() | {"cited_rows": sum(t.citations for t in cited), "max_targets": p.max_targets,
                                    "mirrored": sum(1 for t in p.targets if t.norm in mirrored)},
            "targets": [one(t) for t in p.targets[:top]], "dropped": [one(t) for t in p.dropped[:top or 50]]}


@law.command("targets")
def targets_cmd(top: int = typer.Option(None, help="앞에서 이만큼만 출력"),
                as_json: bool = typer.Option(False, "--json", help="JSON으로 출력")) -> None:
    """미러할 법령 목록(설정 시드 + 내부규정 인용 + 시행령·시행규칙)과 사유·인용 수. DB를 읽기만 한다."""
    from reg.platform.runs import open_conn
    from reg.sources.lawgo.config import load_config

    with open_conn() as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        rep = targets_report(conn, load_config(), top)
        conn.rollback()
    if as_json:
        typer.echo(json.dumps(rep, ensure_ascii=False, indent=2))
        return
    c = rep["counts"]
    typer.echo(f"대상 {c['total']}건 (상한 {c['max_targets']}, 넘쳐서 뺀 것 {c['dropped']}) — 설정 {c['config']} ·"
               f" 인용 {c['cited']} (인용 {c['cited_rows']}회) · 시행령·규칙 {c['child']} · 미러됨 {c['mirrored']}")
    for i, t in enumerate(rep["targets"], 1):
        mark = "*" if t["mirrored"] else " "
        typer.echo(f"{i:5d} {mark} {t['name']}\t{'+'.join(t['reasons'])}\t{t['citations']}")
    if rep["dropped"]:
        typer.echo(f"-- 상한으로 뺀 것 (앞 {len(rep['dropped'])}건) --")
        for t in rep["dropped"]:
            typer.echo(f"        {t['name']}\t{'+'.join(t['reasons'])}\t{t['citations']}")


@law.command("link")
def link_cmd() -> None:
    """내부규정 인용 → 법령 조문 외래키 (reg process 뒤에)."""
    from reg.sources.lawgo import tasks

    _echo(tasks.link)


@law.command("promote")
def promote_cmd() -> None:
    """인용·지정 법령의 새 현행 판본을 regulation.work로 (outbox regulation.law_fetched)."""
    from reg.sources.lawgo import tasks

    _echo(tasks.promote)


@law.command("annex")
def annex_cmd(limit: int = typer.Option(2000, help="이번에 받을 별표 본문 수")) -> None:
    """밀린 별표 본문(HTML·PDF) 받기."""
    from reg.sources.lawgo import tasks

    _echo(tasks.fetch_annexes, limit)


@law.command("status")
def status_cmd(canary: bool = typer.Option(False, "--canary", help="law.go.kr에 최소 요청 3개로 응답 구조 확인")) -> None:
    """미러 현황(법령·조문·별표·카탈로그 수, 최근 실행). --canary면 실연결 점검도 한다."""
    from reg.platform.runs import open_conn
    from reg.platform.settings import get_settings
    from reg.sources.lawgo.client import make_client
    from reg.sources.lawgo.sync import canary as run_canary
    from reg.sources.lawgo.sync import status

    def body() -> dict:
        with open_conn() as conn:
            st = status(conn)
        if canary:
            s = get_settings()
            client = make_client(s.lawgo_oc, s.lawgo_min_interval)
            try:
                st["canary"] = run_canary(client)
            finally:
                client.close()
        return st
    _echo(body)


@law.command("collect")
def collect() -> None:
    """옛 `reg law collect`·`reg collect law`: 이제 `reg law sync`와 같다."""
    from reg.sources.lawgo import tasks

    _echo(tasks.sync_daily, None)
