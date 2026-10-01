import pytest

from reg.llm import ProviderError
from reg.search.indexer import build_release
from reg.search.os import OpenSearch
from reg.search.service import search
from tests.test_indexer import FakeEmbedder


class FakeReranker:
    def rerank(self, q, docs):
        return sorted(((i, 1.0 if "7일 이내에 출장을 확인" in d else 0.0) for i, d in enumerate(docs)), key=lambda x: -x[1])


class DownEmbedder(FakeEmbedder):
    def embed(self, texts):
        raise ProviderError("down")


@pytest.fixture
def indexed(loaded, os_url):
    os = OpenSearch(os_url)
    build_release(loaded, os, FakeEmbedder(), "fake")
    return os


def test_hybrid_with_rerank_finds_deadline_article(indexed):
    r = search(indexed, FakeEmbedder(), FakeReranker(), "출장 증빙 제출 기한", institution="KASI")
    assert r["mode"] == "hybrid" and r["reranked"] and r["hits"][0]["path"].startswith("a27")
    assert all(h["institution"] in ("KASI", None) for h in r["hits"])


def test_bm25_fallback_when_embedder_down(indexed):
    r = search(indexed, DownEmbedder(), None, "증빙서", rerank=False)
    assert r["mode"] == "bm25" and r["hits"]


def test_as_of_filters_versions(indexed):
    assert search(indexed, FakeEmbedder(), None, "증빙서", as_of="1990-01-01", rerank=False)["hits"] == []
    assert search(indexed, FakeEmbedder(), None, "증빙서", as_of="2025-01-01", rerank=False)["hits"]
