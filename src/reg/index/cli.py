"""reg index …: CLI와 DAG가 같은 tasks 함수를 부른다. CLI build는 게이트를 통과하면 게시까지 한다."""
import typer

from reg.index import tasks

index = typer.Typer(no_args_is_help=True, help="검색 색인(게시 버전)")


@index.command("build")
def build_cmd(no_publish: bool = typer.Option(False, "--no-publish", help="빌드·게이트까지만"),
              force: bool = typer.Option(False, "--force", help="변화가 없어도 새로 만든다")) -> None:
    st = tasks.build(force=force)
    if st.get("skipped"):
        typer.echo(f"변화 없음: 게시본 release {st['release_id']} 유지")
        return
    typer.echo(f"built {st}")
    try:
        g = tasks.gate(st["release_id"])
    except tasks.GateFailed as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from e
    typer.echo(f"gate 통과 {g.get('reasons')}")
    if not no_publish:
        typer.echo(f"published {tasks.publish(st['release_id'])}")


@index.command("gate")
def gate_cmd(release_id: int) -> None:
    try:
        typer.echo(f"gate {tasks.gate(release_id)}")
    except tasks.GateFailed as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from e


@index.command("publish")
def publish_cmd(release_id: int) -> None:
    typer.echo(f"published {tasks.publish(release_id)}")


@index.command("prune")
def prune_cmd(dry_run: bool = typer.Option(False, "--dry-run")) -> None:
    from reg.index.os import OpenSearch
    from reg.index.release import prune_releases
    from reg.platform.runs import open_conn
    from reg.platform.settings import get_settings

    if not dry_run:
        typer.echo(f"prune {tasks.prune()}")
        return
    s = get_settings()
    with open_conn() as conn:
        typer.echo(f"prune(dry-run) {prune_releases(conn, OpenSearch(s.os_url), dry_run=True)}")


@index.command("smoke")
def smoke_cmd(index_name: str = typer.Option(None, "--index", help="기본: 지금 alias가 가리키는 색인")) -> None:
    """읽기 전용: 고정 질의를 지정 색인에 던져 적중 여부만 본다 (DB에 쓰지 않는다)."""
    from reg.index.os import OpenSearch
    from reg.index.release import smoke_check
    from reg.platform.llm import EmbeddingProvider, RerankProvider
    from reg.platform.settings import get_settings

    s = get_settings()
    os = OpenSearch(s.os_url, timeout=tasks.GATE_OS_TIMEOUT)
    target = index_name or os.alias_target()
    res = smoke_check(os, EmbeddingProvider(s.embed_url, s.embed_model),
                      RerankProvider(s.rerank_url, s.rerank_model), target, tasks.smoke_cases())
    for r in res:
        typer.echo(f"{'O' if r['hit'] else 'X'} {r['id']} [{r['mode']}] {r['top']}")
    if not all(r["hit"] for r in res):
        raise typer.Exit(1)


@index.command("status")
def status_cmd() -> None:
    from reg.index.os import OpenSearch
    from reg.platform.runs import open_conn
    from reg.platform.settings import get_settings

    s = get_settings()
    with open_conn() as conn:
        for r in conn.execute("SELECT id, state, os_index, stats, created_at FROM ops.release ORDER BY id DESC LIMIT 5"):
            typer.echo(f"{r['id']} {r['state']} {r['os_index']} {r['stats']}")
    os = OpenSearch(s.os_url)
    typer.echo(f"alias → {os.alias_target()} · 색인 {os.indexes()}")
