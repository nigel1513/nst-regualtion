"""검색 집계 (M7 spec §2.2-4): 기관별·종류별·규정별 조 수. 집계는 글자로 맞은 문서(BM25)로 센다:
knn은 언제나 이웃 k개를 돌려주므로 건수의 뜻이 없다. 각 축은 자기 축의 필터만 빼고 센다(다른 기관 수도 보이게).
검색어 낱말 대부분(3개 이상이면 75%)이 맞은 문서만 센다: 낱말 하나만 맞아도 세면 '규정'·'1' 같은 말 때문에
거의 모든 조가 잡힌다 (실색인 2026-10-03)."""
from reg.index.service import base_filters, institution_filter, kind_filter

MIN_MATCH = "2<75%"
# 정식 라벨(full_label)은 빼고 센다: "여비규정 제27조 제1항" 같은 인용 질의에서 모든 규정의 제27조가 잡힌다
FIELDS = ["text^3", "heading^2", "breadcrumb", "article_text"]


def _agg(field: str, size: int, flt: list[dict]) -> dict:
    inner = {"terms": {"field": field, "size": size},
             "aggs": {"articles": {"cardinality": {"field": "article_key"}},
                      "name": {"terms": {"field": "institution_name.kw", "size": 1}}}}
    return {"filter": {"bool": {"filter": flt}}, "aggs": {"v": inner}}


def facets(os, q: str, institution: str | None = None, as_of: str | None = None, kind: str | None = None,
           unit=None, current_only: bool = True, index: str | None = None) -> dict:
    fi, fk = institution_filter(institution), kind_filter(kind)
    query = {"bool": {"must": {"multi_match": {"query": q, "fields": FIELDS, "type": "cross_fields",
                                               "minimum_should_match": MIN_MATCH}},
                      "filter": base_filters(as_of, unit, current_only)}}
    body = {"size": 0, "query": query, "aggs": {
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
