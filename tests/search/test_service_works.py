"""규정·주제 범위 (assistant-scope): work_ids는 OpenSearch 질의 안의 필터다 (BM25·knn·번호 조회 모두)."""
from reg.search.service import search
from tests.index.fakes import FakeEmbedder
from tests.search.test_service_institution import ALIASES, SCHOOL, TRAVEL, FakeOS

WORK = "kr/reg/KASI/여비규정"


def _work_terms(flt: list[dict]) -> list[list[str]]:
    return [f["terms"]["work_id"] for f in flt if "work_id" in f.get("terms", {})]


def test_work_ids_filter_bm25_knn_and_lookup():
    os = FakeOS(hybrid=[TRAVEL], lookup=[TRAVEL])
    r = search(os, FakeEmbedder(), None, "천문연 여비규정 27조", work_ids=[WORK], aliases=ALIASES, rerank=False,
               facets=False)
    hybrid = next(b for b in os.bodies if "hybrid" in b.get("query", {}))
    bm25, knn = hybrid["query"]["hybrid"]["queries"]
    assert _work_terms(bm25["bool"]["filter"]) == [[WORK]]
    assert _work_terms(knn["knn"]["embedding"]["filter"]["bool"]["filter"]) == [[WORK]]
    look = next(b for b in os.bodies
                if any("article_no" in f.get("term", {}) for f in b["query"].get("bool", {}).get("filter", [])))
    assert _work_terms(look["query"]["bool"]["filter"]) == [[WORK]]
    assert r["hits"][0]["work_id"] == WORK


def test_work_ids_alone_allow_number_lookup_without_title_or_institution():
    os = FakeOS(hybrid=[SCHOOL], lookup=[TRAVEL])
    r = search(os, FakeEmbedder(), None, "제27조", work_ids=[WORK], aliases=ALIASES, rerank=False, facets=False)
    assert r["lookup"] and r["hits"][0]["work_id"] == WORK         # 그 규정의 제27조를 1위로


def test_no_work_ids_no_work_filter():
    os = FakeOS(hybrid=[TRAVEL])
    search(os, FakeEmbedder(), None, "출장 증빙", aliases=ALIASES, rerank=False, facets=False)
    assert all(not _work_terms(b.get("query", {}).get("hybrid", {"queries": [{"bool": {"filter": []}}]})
                               ["queries"][0]["bool"]["filter"]) for b in os.bodies if "hybrid" in b.get("query", {}))
