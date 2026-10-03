"""M7 §2.2-2: 조항 단위 후보를 조로 묶고, 맞은 하위 단위와 하이라이트를 돌려준다."""
import pytest

from reg.index.indexer import build_release
from reg.index.service import search
from tests.index.fakes import FakeEmbedder, FakeReranker


@pytest.fixture
def indexed(loaded, osx):
    build_release(loaded, osx, FakeEmbedder(), "fake")
    return osx


def test_grouped_hits_have_matches(indexed):
    r = search(indexed, FakeEmbedder(), None, "증빙서 회계담당부서", institution="KASI", rerank=False, with_units=True)
    h = r["hits"][0]
    assert h["path"] == "a27.p1" and h["article_path"] == "a27" and h["path_label"].startswith("제27조")
    assert h["matches"][0]["path"] == "a27.p1" and "<mark>" in h["matches"][0]["highlight"]
    assert h["text"].startswith("제27조") and [u["path"] for u in h["units"]][:2] == ["a27", "a27.p1"]
    assert len({(x["version_id"], x["article_path"]) for x in r["hits"]}) == len(r["hits"])   # 조마다 한 번


def test_rerank_orders_groups_by_best_unit(indexed):
    r = search(indexed, FakeEmbedder(), FakeReranker(), "출장 증빙 제출 기한", institution="KASI")
    assert r["reranked"] and r["hits"][0]["article_path"] == "a27" and r["hits"][0]["rerank_score"] == 1.0
    assert "units" not in r["hits"][0]


def test_unit_and_kind_filters(indexed):
    r = search(indexed, FakeEmbedder(), None, "증빙서", rerank=False, unit="paragraph")
    assert r["hits"] and all(m["unit"] == "paragraph" for h in r["hits"] for m in h["matches"])
    assert search(indexed, FakeEmbedder(), None, "증빙서", rerank=False, kind="law")["hits"] == []
