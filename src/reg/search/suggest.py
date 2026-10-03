"""규정명 자동완성 (M7 spec §2.2-5): search_as_you_type, 규범문서마다 한 번."""
from reg.index.service import base_filters, institution_filter


def suggest(os, q: str, institution: str | None = None, size: int = 8, index: str | None = None) -> list[dict]:
    q = (q or "").strip()
    if not q:
        return []
    flt = base_filters(current_only=True) + [x for x in (institution_filter(institution),) if x]
    body = {"size": size, "_source": ["title", "work_id", "institution", "institution_name", "family"],
            "query": {"bool": {"filter": flt, "must": {"multi_match": {
                "query": q, "type": "bool_prefix",
                "fields": ["title_suggest", "title_suggest._2gram", "title_suggest._3gram"]}},
                "should": [{"term": {"title.kw": {"value": q, "boost": 5}}}]}},
            "collapse": {"field": "work_id"}, "sort": ["_score", {"title.kw": "asc"}]}
    res = os.search(body, **({"index": index} if index else {}))
    return [{k: h["_source"].get(k) for k in ("title", "work_id", "institution", "institution_name", "family")}
            for h in res["hits"]["hits"]]
