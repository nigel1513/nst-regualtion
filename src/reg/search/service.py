"""하이브리드 검색 (spec 8.2 4단계, 8.5 장애 시 동작)."""
from reg.llm import ProviderError
from reg.search.mapping import PIPELINE

CANDIDATES = 50
FIELDS = ["text^2", "path_label^2", "title", "context_text"]


def _filters(institution: str | None, as_of: str | None, kind: str | None) -> list[dict]:
    f: list[dict] = []
    if as_of:
        f.append({"range": {"effective_from": {"lte": as_of}}})
        f.append({"bool": {"should": [{"range": {"effective_to": {"gt": as_of}}},
                                      {"bool": {"must_not": {"exists": {"field": "effective_to"}}}}],
                           "minimum_should_match": 1}})
    else:
        f.append({"term": {"version_state": "CURRENT"}})
    if kind == "law":
        f.append({"bool": {"must_not": {"term": {"work_kind": "INTERNAL_REG"}}}})
    if institution:
        f.append({"bool": {"should": [{"term": {"institution": institution}},
                                      {"bool": {"must_not": {"term": {"work_kind": "INTERNAL_REG"}}}}],
                           "minimum_should_match": 1}})
    return f


def search(os, embedder, reranker, q: str, institution: str | None = None, as_of: str | None = None,
           kind: str | None = None, rerank: bool = True, size: int = 10) -> dict:
    flt = _filters(institution, as_of, kind)
    bm25 = {"bool": {"must": {"multi_match": {"query": q, "fields": FIELDS}}, "filter": flt}}
    mode = "hybrid"
    try:
        vec = embedder.embed([q])[0]
        body = {"size": CANDIDATES, "_source": {"excludes": ["embedding"]},
                "query": {"hybrid": {"queries": [bm25, {"knn": {"embedding": {
                    "vector": vec, "k": CANDIDATES, "filter": {"bool": {"filter": flt}}}}}]}}}
        res = os.search(body, pipeline=PIPELINE)
    except ProviderError:
        mode = "bm25"
        res = os.search({"size": CANDIDATES, "_source": {"excludes": ["embedding"]}, "query": bm25})
    hits = [{**{k: h["_source"].get(k) for k in ("chunk_id", "work_id", "version_id", "path", "path_label", "title",
                                                  "institution", "text", "release_id")}, "score": h["_score"]}
            for h in res["hits"]["hits"]]
    reranked = False
    if rerank and reranker and hits:
        try:
            order = reranker.rerank(q, [h["text"] for h in hits])
            hits = [{**hits[i], "rerank_score": s} for i, s in order]
            reranked = True
        except ProviderError:
            pass
    release = hits[0].pop("release_id") if hits else None
    for h in hits[1:]:
        h.pop("release_id", None)
    return {"mode": mode, "reranked": reranked, "release_id": release, "hits": hits[:size]}
