"""reg refs — 참조 재해석 (02-data-loading §5.3)."""
import time

import typer

refs = typer.Typer(no_args_is_help=True, help="조문 참조 추출·해석")


@refs.command("reresolve")
def reresolve_cmd(works: list[str] = typer.Option(None, "--works",
                                                  help="규범문서 id (쉼표 구분·반복 가능). 비우면 미해석·모호 참조가 있는 work 전부"),
                  all_works: bool = typer.Option(False, "--all", help="참조 규칙을 바꾼 뒤: 모든 work를 다시 해석"),
                  dry_run: bool = typer.Option(False, "--dry-run", help="쓰지 않고 바뀔 work·참조 수만 센다")) -> None:
    """참조를 다시 해석하고, 결과가 바뀐 work만 다시 쓴다. 쓴 뒤에는 `reg graph sync`로 그래프를 맞춘다."""
    from reg.core.refs import reresolve
    from reg.platform.runs import open_conn, task_run

    ids = [w.strip() for arg in works or [] for w in arg.split(",") if w.strip()] or None
    t0 = time.monotonic()
    with open_conn() as conn:
        if all_works and not ids:
            ids = [r["id"] for r in conn.execute("SELECT id FROM regulation.work ORDER BY id").fetchall()]
        if dry_run:
            st = reresolve(conn, ids, dry_run=True, log=typer.echo)
        else:
            with task_run("core.refs_reresolve", conn) as st:
                st.update(reresolve(conn, ids, log=typer.echo))
    head = " ".join(f"{k}={v}" for k, v in st.items() if k != "failed_works")
    typer.echo(f"refs reresolve{' (dry-run, 쓰지 않음)' if dry_run else ''}: {head} {time.monotonic() - t0:.1f}s")
    for f in st.get("failed_works", []):
        typer.echo(f"  실패 {f}")
    if not dry_run and st["changed"]:
        typer.echo("그래프 반영: reg graph sync")
