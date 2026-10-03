"""검색 집계 (M7 spec §2.2-4): 기관별·종류별·규정별 조 수. 집계는 글자로 맞은 문서(BM25)로 센다:
knn은 언제나 이웃 k개를 돌려주므로 건수의 뜻이 없다. 각 축은 자기 축의 필터만 빼고 센다(다른 기관 수도 보이게)."""
from reg.index.service import base_filters, bm25_query, institution_filter, kind_filter


def _agg(field: str, size: int, flt: list[dict]) -> dict:
    inner = {"terms": {"field": field, "size": size},
             "aggs": {"articles": {"cardinality": {"field": "article_key"}},
                      "name": {"terms": {"field": "institution_name.kw", "size": 1}}}}
    return {"filter": {"bool": {"filter": flt}}, "aggs": {"v": inner}}


def facets(os, q: str, institution: str | None = None, as_of: str | None = None, kind: str | None = None,
           unit=None, current_only: bool = True, index: str | None = None) -> dict:
    fi, fk = institution_filter(institution), kind_filter(kind)
    body = {"size": 0, "query": bm25_query(q, base_filters(as_of, unit, current_only)), "aggs": {
        "institution": _agg("institution", 50, [x for x in (fk,) if x]),
        "kind": _agg("family", 5, [x for x in (fi,) if x]),
        "title": _agg("title.kw", 10, [x for x in (fi, fk) if x])}}
    aggs = os.search(body, **({"index": index} if index else {}))["aggregations"]

    def rows(name: str) -> list[dict]:
        out = []
        for b in aggs[name]["v"]["buckets"]:
            row = {"value": b["key"], "count": b["articles"]["value"]}
            if name == "institution":
                names = b["name"]["buckets"]
                row["name"] = names[0]["key"] if names else b["key"]
            out.append(row)
        return out

    return {"institution": rows("institution"), "kind": rows("kind"), "title": rows("title")}
