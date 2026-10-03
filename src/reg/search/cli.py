"""reg search …: 운영 확인용 (읽기 전용). 색인은 REG_OS_URL의 reg-provisions 별칭을 본다."""
import json
import time

import typer

search_app = typer.Typer(no_args_is_help=True, help="조항 검색 (번호 조회·하이브리드·자동완성)")


def _deps():
    from reg.index.os import OpenSearch
    from reg.platform.llm import EmbeddingProvider, RerankProvider
    from reg.platform.settings import get_settings

    s = get_settings()
    return (OpenSearch(s.os_url), EmbeddingProvider(s.embed_url, s.embed_model, timeout=5, tries=1),
            RerankProvider(s.rerank_url, s.rerank_model, timeout=10))


def _aliases() -> dict[str, list[str]]:
    from reg.platform.runs import open_conn

    with open_conn() as conn:
        rows = conn.execute("SELECT code, name, aliases FROM regulation.institution WHERE active").fetchall()
        conn.rollback()
    return {r["code"]: [r["name"], *(r["aliases"] or []), r["code"]] for r in rows}


@search_app.command("query")
def query_cmd(q: str, institution: str = typer.Option(None), as_of: str = typer.Option(None),
              size: int = typer.Option(5)) -> None:
    from reg.search.service import search

    os, emb, rr = _deps()
    t = time.monotonic()
    r = search(os, emb, rr, q, institution=institution, as_of=as_of, size=size, aliases=_aliases(), with_units=False)
    typer.echo(f"{r['mode']} reranked={r['reranked']} {int((time.monotonic() - t) * 1000)}ms")
    for x in r["lookup"]:
        typer.echo(f"  [조회] {x['full_label']} ({x['work_id']} {x['path']})")
    for h in r["hits"]:
        typer.echo(f"  {h['title']} {h['path_label']} · {[m['label'] for m in h['matches']]} "
                   f"({h.get('rerank_score', h['score']):.3f})")


@search_app.command("lookup")
def lookup_cmd(q: str, as_of: str = typer.Option(None)) -> None:
    from reg.search.lookup import lookup

    r = lookup(_deps()[0], q, _aliases(), as_of=as_of)
    typer.echo(json.dumps(r["citation"], ensure_ascii=False))
    for x in r["hits"]:
        typer.echo(f"  {x['full_label']} ({x['work_id']} {x['path']}) {x['text'][:60]}")


@search_app.command("suggest")
def suggest_cmd(q: str, institution: str = typer.Option(None)) -> None:
    from reg.search.suggest import suggest

    for x in suggest(_deps()[0], q, institution):
        typer.echo(f"  {x['title']} ({x['institution']})")
