"""검색 서비스 (M7 spec §2.2): 조 단위 하이브리드 검색 + 번호 직접 조회 + 집계.
질문이 번호 인용 형태(규정명·기관이 있는 "…제27조 제1항")면 직접 조회 결과를 lookup으로 먼저 준다."""
from reg.index.service import FAMILIES, cited_hit
from reg.index.service import search as engine
from reg.search.citation import mentioned_institution, parse_citation
from reg.search.facets import facets as facet_counts
from reg.search.lookup import lookup


def search(os, embedder, reranker, q: str, *, institution: str | None = None, as_of: str | None = None,
           kind: str | None = None, unit=None, current_only: bool = True, rerank: bool = True, size: int = 10,
           aliases: dict[str, list[str]] | None = None, facets: bool = True, with_units: bool = True,
           index: str | None = None, work_ids: list[str] | set[str] | None = None) -> dict:
    """work_ids: 규정 범위. 하이브리드·번호 조회 모두 그 규정들 안에서 찾는다 (규정이 정해지면 기관도 정해진 셈)."""
    c = parse_citation(q, aliases)
    # 질의가 기관을 하나 말하면(인용 "천문연 여비규정 27조"든 그냥 "천문연 출장 증빙"이든) 하이브리드·집계도 그 기관으로
    # 거른다. 요청에서 고른 기관이 늘 우선이다 (QA resolve_mention과 같은 규칙)
    inst = institution or (c.institution if c and c.institution else mentioned_institution(q, aliases))
    res = engine(os, embedder, reranker, q, institution=inst, as_of=as_of, kind=kind, rerank=rerank,
                 size=size, index=index, unit=unit, current_only=current_only, with_units=with_units,
                 work_ids=work_ids)
    res["citation"] = c.as_dict() if c else None
    res["lookup"] = []
    if c is not None and (c.title or inst or work_ids):
        if inst and not c.institution:
            c.institution = inst
        res["lookup"] = lookup(os, c, as_of=as_of, size=3, index=index, work_ids=work_ids)["hits"]
        top = res["lookup"][0] if res["lookup"] else None
        # 기관까지 정해진 인용이면 그 조가 하이브리드 1위다 (리랭커가 다른 규정의 같은 번호 조를 올려도)
        if top and (inst or work_ids) and (kind not in FAMILIES or top.get("family") in FAMILIES[kind]):
            res["hits"] = _pin(os, res["hits"], top, size, with_units, index)
    if facets:
        res["facets"] = facet_counts(os, q, inst, as_of, kind, unit, current_only, index)
    return res


def _pin(os, hits: list[dict], top: dict, size: int, with_units: bool, index: str | None) -> list[dict]:
    key = (top["version_id"], top["article_path"])
    same = [h for h in hits if (h["version_id"], h.get("article_path")) == key]
    rest = [h for h in hits if (h["version_id"], h.get("article_path")) != key]
    return [same[0] if same else cited_hit(os, top, with_units, index), *rest][:size]
