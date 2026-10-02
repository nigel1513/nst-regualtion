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
