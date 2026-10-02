"""reg graph … — Neo4j 참조 그래프 (PostgreSQL에서 파생)."""
import typer

from reg.platform.db.conn import connect
from reg.platform.neo4j import neo4j_driver as _neo4j
from reg.platform.settings import get_settings

graph = typer.Typer(no_args_is_help=True, help="Neo4j 참조 그래프 (PostgreSQL에서 파생)")


@graph.command("sync")
def graph_sync() -> None:
    from reg.graph.sync import graph_lock, sync_graph

    s = get_settings()
    conn = connect(s.database_url)
    with _neo4j(s) as drv, graph_lock(conn):
        typer.echo(f"graph {sync_graph(conn, drv)}")
