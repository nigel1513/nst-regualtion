"""서비스 UI 개편 §3 규정 보기 오른쪽 레일 "다른 기관의 같은 조항": GET /api/v1/provision/similar (reg-provisions knn)."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from reg.api.app import create_app
from reg.core.ingest.process import process_once
from reg.index.indexer import build_release
from reg.index.os import OpenSearch
from reg.platform.storage.blob import LocalBlobStore
from tests.index.fakes import FakeEmbedder, make_doc
from tests.test_api import WID, S
from tests.test_process import seed_alio


@pytest.fixture
def ctx(conn, migrated, tmp_path, os_url):
    blob = LocalBlobStore(tmp_path)
    seed_alio(conn, blob, (S / "kasi-yeobi-339.pdf").read_bytes())
    process_once(conn, blob, today=date(2026, 10, 2))
    os = OpenSearch(os_url)
    for name in os.indexes():
        os.delete_index(name)
    build_release(conn, os, FakeEmbedder(), "fake")
    index = os.alias_target()
    pv = conn.execute("SELECT pv.id FROM regulation.provision_version pv JOIN regulation.provision p"
                      " ON p.id = pv.provision_id WHERE p.work_id = %s AND pv.path = 'a27'", (WID,)).fetchone()["id"]
    src = os.search({"size": 1, "_source": ["embedding"], "query": {"term": {"pv_id": pv}}})["hits"]["hits"][0]
    vec = src["_source"]["embedding"]
    far = [-x for x in vec]

    def art(doc_id, inst, name, work, title, label, text, emb, **over):
        return make_doc(doc_id=doc_id, pv_id=10_000 + len(doc_id), institution=inst, institution_name=name,
                        work_id=work, version_id=f"{work}@v", title=title, path=label, base_path=label,
                        parent_path=None, article_path=label, article_key=f"{work}@v|{label}", unit="article",
                        label=f"제{label[1:]}조", full_label=f"{title} 제{label[1:]}조", heading="출장증빙",
                        text=text, article_text=f"제{label[1:]}조(출장증빙)\n{text}", embedding=emb, **over)

    os.bulk(index, [
        art("e1", "ETRI", "한국전자통신연구원", "kr/reg/ETRI/여비규정", "여비규정", "a30", "출장 후 5일 이내에 증빙을 낸다.", vec),
        art("e2", "ETRI", "한국전자통신연구원", "kr/reg/ETRI/여비규정", "여비규정", "a31", "다른 조문", far),
        art("k1", "KIST", "한국과학기술연구원", "kr/reg/KIST/여비지침", "여비지침", "a12", "출장 후 10일 이내 제출.", vec),
        art("k2", "KIST", "한국과학기술연구원", "kr/reg/KIST/옛여비", "옛여비", "a3", "옛 판본", vec,
            version_state="HISTORICAL"),
        art("s1", "KASI", "한국천문연구원", "kr/reg/KASI/다른규정", "다른규정", "a9", "같은 기관", vec),
        art("l1", None, None, "kr/law/001", "법", "a5", "법령 조문", vec, family="law"),
    ])
    os.refresh(index)
    deps = {"os": os, "embedder": FakeEmbedder(), "reranker": None}
    with TestClient(create_app(migrated[0], blob, deps)) as c:
        yield c, pv


def test_similar_returns_other_institutions_current_articles(ctx):
    api, pv = ctx
    r = api.get("/api/v1/provision/similar", params={"pv": pv, "limit": 5})
    assert r.status_code == 200
    d = r.json()
    assert d["source"]["institution"] == "KASI" and d["source"]["work_id"] == WID
    items = d["items"]
    insts = [x["institution"] for x in items]
    assert "KASI" not in insts and None not in insts                     # 같은 기관·법령 제외
    assert all(x["title"] != "옛여비" for x in items)                     # 현행만
    top = items[0]
    assert top["institution"] in ("ETRI", "KIST") and top["institution_name"]
    assert {"work_id", "title", "label", "heading", "snippet", "href", "article_path", "score"} <= set(top)
    assert top["href"].startswith("/regulations/kr/reg/") and "?a=" in top["href"]
    assert insts[:2] in (["ETRI", "KIST"], ["KIST", "ETRI"])               # 기관마다 하나씩 먼저
    assert not top["snippet"].startswith("제")                           # 조 머리말은 빼고 본문만


def test_similar_limit_and_errors(ctx):
    api, pv = ctx
    assert len(api.get("/api/v1/provision/similar", params={"pv": pv, "limit": 1}).json()["items"]) == 1
    assert api.get("/api/v1/provision/similar", params={"pv": 999_999_999}).status_code == 404
    assert api.get("/api/v1/provision/similar", params={"pv": pv, "limit": 50}).status_code == 422


def test_similar_503_without_index(migrated, tmp_path):
    with TestClient(create_app(migrated[0], LocalBlobStore(tmp_path))) as c:
        assert c.get("/api/v1/provision/similar", params={"pv": 1}).status_code == 503
