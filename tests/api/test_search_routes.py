"""M7 §2.2 API: /api/v1/hsearch(조 묶음·matches·집계·번호 조회), /api/v1/search/lookup, /api/v1/search/suggest."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from reg.api.app import create_app
from reg.core.ingest.process import process_once
from reg.index.indexer import build_release
from reg.index.os import OpenSearch
from reg.platform.storage.blob import LocalBlobStore
from tests.index.fakes import FakeEmbedder
from tests.test_api import S
from tests.test_process import seed_alio


@pytest.fixture
def api(conn, migrated, tmp_path, os_url):
    blob = LocalBlobStore(tmp_path)
    seed_alio(conn, blob, (S / "kasi-yeobi-339.pdf").read_bytes())
    process_once(conn, blob, today=date(2026, 10, 2))
    conn.execute("UPDATE regulation.institution SET aliases = '{천문연}' WHERE code = 'KASI'")
    conn.commit()
    os = OpenSearch(os_url)
    for name in os.indexes():
        os.delete_index(name)
    build_release(conn, os, FakeEmbedder(), "fake")
    deps = {"os": os, "embedder": FakeEmbedder(), "reranker": None}
    with TestClient(create_app(migrated[0], blob, deps)) as c:
        yield c


def test_hsearch_returns_grouped_hits_with_old_fields(api):
    r = api.get("/api/v1/hsearch", params={"q": "증빙서 회계담당부서", "institution": "KASI", "rerank": "false"}).json()
    h = r["hits"][0]
    for k in ("chunk_id", "work_id", "version_id", "path", "path_label", "title", "institution", "text", "score"):
        assert k in h
    assert h["article_path"] == "a27" and h["matches"][0]["path"] == "a27.p1" and h["matches"][0]["highlight"]
    assert {"path", "label", "highlight"} <= set(h["matches"][0]) and h["units"]
    assert r["facets"]["institution"][0]["value"] == "KASI" and r["lookup"] == []


def test_hsearch_citation_form_puts_lookup_on_top(api):
    r = api.get("/api/v1/hsearch", params={"q": "천문연 여비규정 27조 1항", "rerank": "false"}).json()
    assert r["citation"]["institution"] == "KASI" and r["lookup"][0]["path"] == "a27.p1"


def test_lookup_and_suggest_routes(api):
    r = api.get("/api/v1/search/lookup", params={"q": "여비규정 제27조 제1항"}).json()
    assert r["hits"][0]["full_label"] == "여비규정 제27조 제1항"
    assert api.get("/api/v1/search/lookup", params={"q": "출장 증빙"}).json() == {"citation": None, "hits": []}
    s = api.get("/api/v1/search/suggest", params={"q": "여비"}).json()
    assert s[0]["title"] == "여비규정"
    assert api.get("/api/v1/hsearch", params={"q": "증빙", "kind": "bogus"}).status_code == 422


def test_routes_503_without_index(migrated, tmp_path, os_url):
    os = OpenSearch(os_url)
    for name in os.indexes():
        os.delete_index(name)
    deps = {"os": os, "embedder": FakeEmbedder(), "reranker": None}
    with TestClient(create_app(migrated[0], LocalBlobStore(tmp_path), deps)) as c:
        assert c.get("/api/v1/search/lookup", params={"q": "여비규정 제27조"}).status_code == 503
        assert c.get("/api/v1/search/suggest", params={"q": "여비"}).status_code == 503
        assert c.get("/api/v1/hsearch", params={"q": "여비"}).status_code == 503
