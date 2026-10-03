"""M7 §2.2 끝에서 끝까지: 천문연 여비규정(실파일)을 조항 단위로 색인하고 번호 조회·하이라이트·집계·자동완성을 본다."""
import pytest

from reg.index.indexer import build_release
from reg.index.os import OpenSearch
from reg.search.lookup import lookup
from reg.search.service import search
from reg.search.suggest import suggest
from tests.index.fakes import FakeEmbedder

ALIASES = {"KASI": ["한국천문연구원", "천문연구원", "천문연", "KASI"]}


@pytest.fixture
def indexed(loaded, os_url):
    os = OpenSearch(os_url)
    for name in os.indexes():
        os.delete_index(name)
    build_release(loaded, os, FakeEmbedder(), "fake")
    return os


def test_lookup_returns_paragraph_first(indexed):
    r = lookup(indexed, "여비규정 제27조 제1항", ALIASES)
    top = r["hits"][0]
    assert top["path"] == "a27.p1" and top["unit"] == "paragraph" and top["full_label"] == "여비규정 제27조 제1항"
    assert r["citation"]["article"] == 27 and r["citation"]["paragraph"] == 1
    assert lookup(indexed, "천문연 여비규정 27조", ALIASES)["hits"][0]["path"] == "a27"


def test_lookup_relaxes_missing_paragraph_to_article(indexed):
    r = lookup(indexed, "여비규정 제2조 제1항", ALIASES)          # 제2조는 항이 없는 조: 조를 돌려준다
    assert r["hits"][0]["path"] == "a2" and r["relaxed"] is True
    assert lookup(indexed, "여비규정 제27조 제1항", ALIASES)["relaxed"] is False


def test_lookup_without_institution_returns_candidates(indexed):
    r = lookup(indexed, "여비규정 제27조", None)
    assert r["hits"] and r["hits"][0]["title"] == "여비규정" and r["hits"][0]["path"] == "a27"
    assert lookup(indexed, "여비규정 제999조", ALIASES)["hits"] == []
    assert lookup(indexed, "출장 증빙 기한", ALIASES)["hits"] == []


def _first_item(conn):
    return conn.execute(
        "SELECT pv.path, pv.text FROM regulation.version_provision vp"
        " JOIN regulation.provision_version pv ON pv.id = vp.provision_version_id"
        " JOIN regulation.work_version v ON v.id = vp.work_version_id"
        " WHERE v.version_state = 'CURRENT' AND pv.unit = 'item' AND length(pv.text) > 12"
        " ORDER BY vp.ord LIMIT 1").fetchone()


def test_phrase_inside_item_highlights_that_item(indexed, loaded):
    item = _first_item(loaded)
    phrase = item["text"][:14].strip()
    r = search(indexed, FakeEmbedder(), None, phrase, institution="KASI", rerank=False, facets=False)
    art = item["path"].split(".")[0]
    group = next(h for h in r["hits"] if h["article_path"] == art)
    m = next(x for x in group["matches"] if x["path"] == item["path"])
    assert m["unit"] == "item" and "<mark>" in m["highlight"]
    assert any(u["path"] == item["path"] for u in group["units"])


def test_citation_query_puts_lookup_first(indexed):
    r = search(indexed, FakeEmbedder(), None, "천문연 여비규정 제27조 제1항", aliases=ALIASES, rerank=False)
    assert r["citation"]["institution"] == "KASI" and r["lookup"][0]["path"] == "a27.p1"
    assert {x["value"] for x in r["facets"]["institution"]} == {"KASI"}
    assert r["facets"]["kind"][0]["value"] == "reg" and r["facets"]["title"][0]["value"] == "여비규정"


def test_suggest_titles(indexed):
    got = suggest(indexed, "여비")
    assert got and got[0]["title"] == "여비규정" and len({g["work_id"] for g in got}) == len(got)
    assert suggest(indexed, "") == []
