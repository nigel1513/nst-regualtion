"""조문 번호 직접 조회 (M7 spec §2.2-1): 인용을 번호 필드 term 조회로 바꾼다. 규정명은 정확히 같으면 1위로."""
from reg.index.service import SOURCE, filters
from reg.search.citation import Citation, parse_citation


def citation_query(c: Citation, as_of: str | None = None) -> dict:
    flt = filters(c.institution, as_of, unit=c.unit())
    flt.append({"bool": {"must_not": {"range": {"window": {"gt": 1}}}}})       # 긴 단위는 첫 창만
    if c.annex is not None:
        flt.append({"term": {"annex_no": c.annex}})
    else:
        flt += [{"term": {"article_no": c.article}}, {"term": {"article_branch": c.branch or 0}}]
        if c.paragraph is not None:
            flt.append({"term": {"paragraph_no": c.paragraph}})
        if c.item is not None:
            flt += [{"term": {"item_no": c.item}}, {"term": {"item_branch": c.item_branch or 0}}]
        if c.subitem:
            flt.append({"term": {"subitem": c.subitem}})
    must = []
    if c.title:
        compact = c.title.replace(" ", "")
        must.append({"bool": {"should": [
            {"term": {"title.kw": {"value": c.title, "boost": 20}}},
            {"term": {"title.kw": {"value": compact, "boost": 20}}},
            {"match_phrase": {"title": {"query": c.title, "boost": 5}}},
            {"match": {"title": {"query": c.title, "operator": "and", "boost": 2}}},
            {"match": {"title": {"query": c.title, "minimum_should_match": "60%"}}}], "minimum_should_match": 1}})
    return {"bool": {"filter": flt, **({"must": must} if must else {})}}


def _hit(h: dict) -> dict:
    s = h["_source"]
    keys = ("doc_id", "work_id", "version_id", "article_path", "unit", "label", "marker", "full_label", "title", "heading",
            "institution", "institution_name", "family", "effective_from", "version_state", "text", "article_text")
    return {**{k: s.get(k) for k in keys}, "path": s["base_path"], "score": h["_score"]}


def lookup(os, q: str | Citation, aliases: dict[str, list[str]] | None = None, as_of: str | None = None,
           size: int = 5, index: str | None = None) -> dict:
    c = q if isinstance(q, Citation) else parse_citation(q, aliases)
    if c is None:
        return {"citation": None, "hits": []}
    kw = {"index": index} if index else {}
    res = os.search({"size": size, "_source": SOURCE, "query": citation_query(c, as_of),
                     "sort": ["_score", {"title.kw": "asc"}, {"ord": "asc"}]}, **kw)
    return {"citation": c.as_dict(), "hits": [_hit(h) for h in res["hits"]["hits"]]}
