"""조 단위로 묶은 하이브리드 검색 (M7 spec §2.2-2, spec 8.5 장애 시 동작).

후보는 조항 단위 문서(조·항·호·목·별표…)다. BM25+knn 하이브리드로 후보를 모으고, 리랭크한 뒤 소속 조(article_key)
별로 묶는다. OpenSearch 2.19는 hybrid 질의 아래 collapse·inner_hits를 받지 않으므로(전용 클러스터에서 확인) 묶음은
여기서 한다. 각 조 묶음은 맞은 하위 단위(matches: 경로·라벨·하이라이트)와, 원하면 조 전체 단위(units)를 함께 준다.
옛 청크 검색의 필드(chunk_id, path, path_label, text, score, rerank_score…)는 그대로 둔다 (QA·게이트·웹 호환)."""
from reg.index.mapping import PIPELINE
from reg.platform.llm import ProviderError

CANDIDATES = 100          # 하이브리드 후보 (조항 단위라 조 청크 때보다 넉넉히)
RERANK_TOP = 40           # 리랭크하는 후보 수 (p95 < 1.5초)
MAX_MATCHES = 5
FIELDS = ["text^3", "heading^2", "full_label", "breadcrumb", "article_text"]
HIGHLIGHT = {"pre_tags": ["<mark>"], "post_tags": ["</mark>"], "fields": {"text": {"number_of_fragments": 0}}}
SOURCE = {"excludes": ["embedding", "title_suggest"]}
FAMILIES = {"reg": ["reg"], "law": ["law", "admrul"], "admrul": ["admrul"]}


def base_filters(as_of: str | None = None, unit: str | list[str] | None = None, current_only: bool = True) -> list[dict]:
    f: list[dict] = []
    if as_of:
        f.append({"range": {"effective_from": {"lte": as_of}}})
        f.append({"bool": {"should": [{"range": {"effective_to": {"gt": as_of}}},
                                      {"bool": {"must_not": {"exists": {"field": "effective_to"}}}}],
                           "minimum_should_match": 1}})
    elif current_only:
        f.append({"term": {"version_state": "CURRENT"}})
    if unit:
        f.append({"terms": {"unit": [unit] if isinstance(unit, str) else list(unit)}})
    return f


def institution_filter(institution: str | None) -> dict | None:
    """코드·정식명·약칭 어느 것이든 (overview §2.8). 법령·행정규칙은 늘 함께 나온다."""
    if not institution:
        return None
    return {"bool": {"should": [{"term": {"institution": institution}},
                                {"term": {"institution_name.kw": institution}},
                                {"term": {"institution_aliases": institution}},
                                {"bool": {"must_not": {"term": {"family": "reg"}}}}],
                     "minimum_should_match": 1}}


def kind_filter(kind: str | None) -> dict | None:
    """kind: reg(내부규정) | law(법령·행정규칙) | admrul(행정규칙)."""
    return {"terms": {"family": FAMILIES[kind]}} if kind in FAMILIES else None


def filters(institution: str | None = None, as_of: str | None = None, kind: str | None = None,
            unit: str | list[str] | None = None, current_only: bool = True) -> list[dict]:
    return base_filters(as_of, unit, current_only) + [x for x in (institution_filter(institution), kind_filter(kind)) if x]


def bm25_query(q: str, flt: list[dict]) -> dict:
    # 질문의 기관명은 institution_name에도 맞춘다 (overview §2.8). must가 아닌 가산점이라 본문 순위는 그대로다.
    return {"bool": {"must": {"multi_match": {"query": q, "fields": FIELDS}},
                     "should": [{"match": {"institution_name": q}}], "filter": flt}}


def _unit(h: dict) -> dict:
    hl = (h.get("highlight") or {}).get("text")
    return {**h["_source"], "score": h["_score"], "highlight": hl[0] if hl else None}


def _rerank_text(u: dict) -> str:
    """리랭커 입력: 규정명 + 조 머리·상위 항(문맥) + 이 단위. 조 문서는 조 전체 본문."""
    body = u.get("article_text") or f"{u.get('marker') or ''} {u.get('text') or ''}".strip()
    return f"{u.get('title') or ''} {u.get('context') or ''}\n{body}"[:1500]


def _rank(u: dict, reranked: bool) -> tuple:
    return (1, u["rerank_score"], u["score"]) if reranked and "rerank_score" in u else (0, u["score"], 0.0)


def _group(units: list[dict], reranked: bool) -> list[list[dict]]:
    groups: dict[str, list[dict]] = {}
    for u in units:
        groups.setdefault(u["article_key"], []).append(u)
    for g in groups.values():
        g.sort(key=lambda u: _rank(u, reranked), reverse=True)
    return sorted(groups.values(), key=lambda g: _rank(g[0], reranked), reverse=True)


def _fetch_units(os, keys: list[str], kw: dict) -> dict[str, list[dict]]:
    """묶음으로 고른 조들의 모든 단위 (조 본문·카드용), 문서 순서(ord)로."""
    if not keys:
        return {}
    res = os.search({"size": 2000, "_source": SOURCE, "query": {"bool": {"filter": [{"terms": {"article_key": keys}}]}},
                     "sort": [{"ord": "asc"}, {"window": "asc"}]}, **kw)
    out: dict[str, list[dict]] = {}
    for h in res["hits"]["hits"]:
        out.setdefault(h["_source"]["article_key"], []).append(h["_source"])
    return out


def _match(u: dict) -> dict:
    return {"path": u["base_path"], "label": u.get("label"), "unit": u.get("unit"), "highlight": u.get("highlight"),
            "score": u["score"], **({"rerank_score": u["rerank_score"]} if "rerank_score" in u else {})}


def _hit(g: list[dict], all_units: list[dict], with_units: bool) -> dict:
    best = g[0]
    art = best["article_path"]
    top = next((u for u in all_units if u["base_path"] == art and u.get("window", 0) <= 1), None)
    text = (top or {}).get("article_text") or best.get("text") or ""
    picked, seen = [], set()
    for u in g:                                   # 가장 잘 맞은 단위 + 하이라이트가 있는 단위
        if u["base_path"] in seen or not (u is best or u.get("highlight")):
            continue
        seen.add(u["base_path"])
        picked.append(_match(u))
        if len(picked) >= MAX_MATCHES:
            break
    out = {"chunk_id": best["article_key"], "doc_id": best["doc_id"], "work_id": best["work_id"],
           "version_id": best["version_id"], "path": best["base_path"], "article_path": art,
           "path_label": text.split("\n", 1)[0] if top else best.get("label"), "full_label": best.get("full_label"),
           "title": best.get("title"), "institution": best.get("institution"),
           "institution_name": best.get("institution_name"), "family": best.get("family"),
           "work_kind": best.get("work_kind"), "version_state": best.get("version_state"),
           "effective_from": best.get("effective_from"), "text": text, "score": best["score"], "matches": picked,
           "release_id": best.get("release_id")}
    if "rerank_score" in best:
        out["rerank_score"] = best["rerank_score"]
    if with_units:
        out["units"] = [{"path": u["base_path"], "unit": u["unit"], "label": u.get("label"), "marker": u.get("marker"),
                         "heading": u.get("heading"), "text": u.get("text") or "", "window": u.get("window", 0),
                         "parent_path": u.get("parent_path")} for u in all_units]
    return out


def cited_hit(os, u: dict, with_units: bool = False, index: str | None = None) -> dict:
    """번호 조회(lookup)로 찾은 단위 하나 → 하이브리드 결과와 같은 모양의 조 묶음. 인용한 조를 1위로 둘 때 쓴다."""
    key = f"{u['version_id']}|{u['article_path']}"
    best = {**u, "base_path": u["path"], "article_key": key, "highlight": None}
    fetched = _fetch_units(os, [key], {"index": index} if index else {})
    out = _hit([best], fetched.get(key, []), with_units)
    out.pop("release_id", None)
    return out


def search(os, embedder, reranker, q: str, institution: str | None = None, as_of: str | None = None,
           kind: str | None = None, rerank: bool = True, size: int = 10, index: str | None = None,
           unit: str | list[str] | None = None, current_only: bool = True, with_units: bool = False) -> dict:
    flt = filters(institution, as_of, kind, unit, current_only)
    bm25 = bm25_query(q, flt)
    kw = {"index": index} if index else {}      # 게이트는 게시 전 색인을 직접 본다
    mode = "hybrid"
    try:
        vec = embedder.embed([q])[0]
        body = {"size": CANDIDATES, "_source": SOURCE, "highlight": HIGHLIGHT,
                "query": {"hybrid": {"queries": [bm25, {"knn": {"embedding": {
                    "vector": vec, "k": CANDIDATES, "filter": {"bool": {"filter": flt}}}}}]}}}
        res = os.search(body, pipeline=PIPELINE, **kw)
    except ProviderError:
        mode = "bm25"
        res = os.search({"size": CANDIDATES, "_source": SOURCE, "highlight": HIGHLIGHT, "query": bm25}, **kw)
    units = [_unit(h) for h in res["hits"]["hits"]]
    reranked = False
    if rerank and reranker and units:
        top = units[:RERANK_TOP]
        try:
            scores = reranker.rerank(q, [_rerank_text(u) for u in top])
            for i, s in scores:
                top[i]["rerank_score"] = s
            reranked = True
        except ProviderError:
            pass
    groups = _group(units, reranked)[:size]
    fetched = _fetch_units(os, [g[0]["article_key"] for g in groups], kw)
    hits = [_hit(g, fetched.get(g[0]["article_key"], []), with_units) for g in groups]
    release = hits[0].get("release_id") if hits else None
    for h in hits:
        h.pop("release_id", None)
    return {"mode": mode, "reranked": reranked, "release_id": release, "hits": hits}
