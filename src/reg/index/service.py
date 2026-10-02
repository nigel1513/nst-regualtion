"""하이브리드 검색 (spec 8.2 4단계, 8.5 장애 시 동작)."""
from reg.index.mapping import PIPELINE
from reg.platform.llm import ProviderError

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
    if institution:  # 코드·정식명·약칭 어느 것이든 (overview §2.8). 법령·행정규칙은 늘 함께 나온다
        f.append({"bool": {"should": [{"term": {"institution": institution}},
                                      {"term": {"institution_name.kw": institution}},
                                      {"term": {"institution_aliases": institution}},
                                      {"bool": {"must_not": {"term": {"work_kind": "INTERNAL_REG"}}}}],
                           "minimum_should_match": 1}})
    return f


def search(os, embedder, reranker, q: str, institution: str | None = None, as_of: str | None = None,
           kind: str | None = None, rerank: bool = True, size: int = 10, index: str | None = None) -> dict:
    flt = _filters(institution, as_of, kind)
    # 질문의 기관명은 institution_name에도 맞춘다 (overview §2.8). must가 아닌 가산점이라 본문 순위는 그대로다.
    bm25 = {"bool": {"must": {"multi_match": {"query": q, "fields": FIELDS}},
                     "should": [{"match": {"institution_name": q}}], "filter": flt}}
    kw = {"index": index} if index else {}      # 게이트는 게시 전 색인을 직접 본다
    mode = "hybrid"
    try:
        vec = embedder.embed([q])[0]
        body = {"size": CANDIDATES, "_source": {"excludes": ["embedding"]},
                "query": {"hybrid": {"queries": [bm25, {"knn": {"embedding": {
                    "vector": vec, "k": CANDIDATES, "filter": {"bool": {"filter": flt}}}}}]}}}
        res = os.search(body, pipeline=PIPELINE, **kw)
    except ProviderError:
        mode = "bm25"
        res = os.search({"size": CANDIDATES, "_source": {"excludes": ["embedding"]}, "query": bm25}, **kw)
    hits = [{**{k: h["_source"].get(k) for k in ("chunk_id", "work_id", "version_id", "path", "path_label", "title",
                                                  "institution", "institution_name", "text", "release_id")}, "score": h["_score"]}
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
