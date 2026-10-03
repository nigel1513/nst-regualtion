"""reg graph … — Neo4j 법령·규정 구조 그래프 (PostgreSQL에서 파생, spec 2026-10-03 §1.2)."""
import time

import typer

from reg.platform.db.conn import connect
from reg.platform.neo4j import neo4j_driver as _neo4j
from reg.platform.settings import get_settings

graph = typer.Typer(no_args_is_help=True, help="Neo4j 법령·규정 구조 그래프 (PostgreSQL에서 파생)")


@graph.command("rebuild")
def graph_rebuild() -> None:
    """그래프를 비우고 모든 규범문서·판본을 다시 넣는다."""
    from reg.graph.sync import graph_lock, rebuild

    s = get_settings()
    t0 = time.monotonic()
    with connect(s.database_url) as conn, _neo4j(s) as drv, graph_lock(conn):  # 닫을 때 읽기 트랜잭션도 끝낸다
        st = rebuild(conn, drv)
    typer.echo(f"graph rebuild {st} {time.monotonic() - t0:.1f}s → {s.neo4j_url}")


@graph.command("sync")
def graph_sync(works: list[str] = typer.Option(None, "--works",
                                               help="규범문서 id (쉼표 구분·반복 가능). 비우면 바뀐 규범문서만")) -> None:
    """규범문서 단위 증분: 지정한 문서, 또는 PostgreSQL과 지문이 다른 문서의 하위 그래프를 다시 넣는다."""
    from reg.graph.sync import graph_lock, sync_changed, sync_works

    ids = [w.strip() for arg in works or [] for w in arg.split(",") if w.strip()]
    s = get_settings()
    t0 = time.monotonic()
    with connect(s.database_url) as conn, _neo4j(s) as drv, graph_lock(conn):
        st = sync_works(conn, drv, ids) if ids else sync_changed(conn, drv)
    typer.echo(f"graph sync {st} {time.monotonic() - t0:.1f}s → {s.neo4j_url}")


@graph.command("stats")
def graph_stats_cmd() -> None:
    from reg.graph.sync import graph_stats

    s = get_settings()
    with _neo4j(s) as drv:
        typer.echo(f"graph {graph_stats(drv)} → {s.neo4j_url}")
