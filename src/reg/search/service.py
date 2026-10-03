"""검색 서비스 (M7 spec §2.2): 조 단위 하이브리드 검색 + 번호 직접 조회 + 집계.
질문이 번호 인용 형태(규정명·기관이 있는 "…제27조 제1항")면 직접 조회 결과를 lookup으로 먼저 준다."""
from reg.index.service import search as engine
from reg.search.citation import parse_citation
from reg.search.facets import facets as facet_counts
from reg.search.lookup import lookup


def search(os, embedder, reranker, q: str, *, institution: str | None = None, as_of: str | None = None,
           kind: str | None = None, unit=None, current_only: bool = True, rerank: bool = True, size: int = 10,
           aliases: dict[str, list[str]] | None = None, facets: bool = True, with_units: bool = True,
           index: str | None = None) -> dict:
    c = parse_citation(q, aliases)
    # 번호 인용에 기관이 있으면("천문연 여비규정 27조") 하이브리드·집계도 그 기관으로 거른다 (명시한 기관이 우선)
    inst = institution or (c.institution if c else None)
    res = engine(os, embedder, reranker, q, institution=inst, as_of=as_of, kind=kind, rerank=rerank,
                 size=size, index=index, unit=unit, current_only=current_only, with_units=with_units)
    res["citation"] = c.as_dict() if c else None
    res["lookup"] = []
    if c is not None and (c.title or inst):
        if inst and not c.institution:
            c.institution = inst
        res["lookup"] = lookup(os, c, as_of=as_of, size=3, index=index)["hits"]
    if facets:
        res["facets"] = facet_counts(os, q, inst, as_of, kind, unit, current_only, index)
    return res
