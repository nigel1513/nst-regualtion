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


def _expected() -> list[dict]:
    import yaml

    from reg.platform.settings import ROOT

    cases = yaml.safe_load((ROOT / "eval/qa_cases.yaml").read_text(encoding="utf-8"))
    out = {}
    for c in cases:
        e = c["expect"]
        if "article" in e and e.get("institution"):
            out[(e["institution"], e["work_contains"], e["article"])] = c
    return [{"institution": k[0], "work_contains": k[1], "article": k[2]} for k in out]


@search_app.command("check-lookups")
def check_lookups_cmd() -> None:
    """M7 spec §3: 평가 세트의 기대 조문을 "기관 규정명 제N조 제M항"으로 넣으면 1위인가 (읽기 전용)."""
    from reg.search.lookup import lookup

    os = _deps()[0]
    aliases = _aliases()
    bad = 0
    for e in _expected():
        r = os.search({"size": 1, "_source": ["title", "institution_name", "work_id"], "query": {"bool": {"filter": [
            {"term": {"version_state": "CURRENT"}}, {"term": {"institution": e["institution"]}},
            {"wildcard": {"work_id": f"*{e['work_contains']}*"}}, {"term": {"article_path": e["article"]}}]}},
            "sort": [{"ord": "asc"}]})["hits"]["hits"]
        if not r:
            typer.echo(f"X {e} 색인에 없음")
            bad += 1
            continue
        s = r[0]["_source"]
        para = os.search({"size": 1, "_source": ["base_path"], "query": {"bool": {"filter": [
            {"term": {"work_id": s["work_id"]}}, {"term": {"version_state": "CURRENT"}},
            {"term": {"article_path": e["article"]}}, {"term": {"unit": "paragraph"}}]}},
            "sort": [{"ord": "asc"}]})["hits"]["hits"]
        art = e["article"][1:].split("-")
        q = f"{s['institution_name']} {s['title']} 제{art[0]}조" + (f"의{art[1]}" if len(art) > 1 else "")
        want = e["article"]
        if para:
            want = para[0]["_source"]["base_path"]
            q += f" 제{int(want.split('.p')[1].split('.')[0].split('~')[0])}항"
        top = (lookup(os, q, aliases)["hits"] or [{}])[0]
        ok = top.get("work_id") == s["work_id"] and top.get("path") == want
        bad += not ok
        typer.echo(f"{'O' if ok else 'X'} {q} → {top.get('work_id')} {top.get('path')}")
    if bad:
        raise typer.Exit(1)


@search_app.command("bench")
def bench_cmd(rounds: int = typer.Option(3)) -> None:
    """검색 지연 p50/p95 (ms): 평가 질문·번호 조회 질의를 rounds번 (읽기 전용)."""
    import yaml

    from reg.platform.settings import ROOT
    from reg.search.service import search

    os, emb, rr = _deps()
    aliases = _aliases()
    qs = [(c["question"], c["expect"].get("institution"))
          for c in yaml.safe_load((ROOT / "eval/qa_cases.yaml").read_text(encoding="utf-8"))]
    qs += [("천문연 여비규정 27조 1항", None), ("NST 여비규정 제9조의2", None), ("출장비 정산 기한", None),
           ("연차 사용 촉진", "NST"), ("법인카드 사용 제한", None), ("재해구호휴가", None)]
    lat = []
    for _ in range(rounds):
        for q, inst in qs:
            t = time.monotonic()
            search(os, emb, rr, q, institution=inst, aliases=aliases)
            lat.append((time.monotonic() - t) * 1000)
    lat.sort()

    def p(x: float) -> float:
        return lat[min(len(lat) - 1, round(x * (len(lat) - 1)))]

    typer.echo(f"n={len(lat)} p50={p(0.5):.0f}ms p95={p(0.95):.0f}ms max={lat[-1]:.0f}ms")
