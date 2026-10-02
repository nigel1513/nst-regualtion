"""reg index … — 검색 색인 (게시 버전)."""
import typer

from reg.platform.db.conn import connect
from reg.platform.settings import get_settings

index = typer.Typer(no_args_is_help=True, help="검색 색인(게시 버전)")


@index.command("build")
def index_build(no_publish: bool = typer.Option(False, "--no-publish")) -> None:
    from reg.index.indexer import build_release
    from reg.index.os import OpenSearch
    from reg.platform.llm import EmbeddingProvider

    s = get_settings()
    conn = connect(s.database_url)
    st = build_release(conn, OpenSearch(s.os_url), EmbeddingProvider(s.embed_url, s.embed_model), s.embed_model,
                       publish=not no_publish)
    typer.echo(f"release {st}")


@index.command("status")
def index_status() -> None:
    from reg.index.os import OpenSearch

    s = get_settings()
    conn = connect(s.database_url)
    for r in conn.execute("SELECT id, state, os_index, stats, created_at FROM ops.release ORDER BY id DESC LIMIT 5"):
        typer.echo(f"{r['id']} {r['state']} {r['os_index']} {r['stats']}")
    typer.echo(f"alias → {OpenSearch(s.os_url).alias_target()}")
