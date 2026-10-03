import pytest

from reg.index.cache import embed_cached, text_hash
from reg.index.service import search
from tests.index.fakes import FakeEmbedder, make_doc

DOC = make_doc()


def _rows(conn, model):
    return conn.execute("SELECT count(*) AS n FROM ops.embedding_cache WHERE model = %s", (model,)).fetchone()["n"]


def test_embed_cached_embeds_only_misses(conn):
    e = FakeEmbedder()
    texts = {text_hash(t): t for t in ["가", "나다", "라마바"]}
    vecs, miss = embed_cached(conn, e, "fake", texts)
    assert miss == 3 and e.texts == 3 and set(vecs) == set(texts)
    more = {**texts, text_hash("사아"): "사아"}
    vecs2, miss2 = embed_cached(conn, e, "fake", more)
    assert miss2 == 1 and e.texts == 4
    assert vecs2[text_hash("가")] == [1.0, 1.0, 0.5, 0.25]      # 캐시(real[])에서 읽어도 같은 값
    assert _rows(conn, "fake") == 4


def test_cache_is_per_model(conn):
    texts = {text_hash("가"): "가"}
    embed_cached(conn, FakeEmbedder(), "fake", texts)
    _, miss = embed_cached(conn, FakeEmbedder(), "other-model", texts)
    assert miss == 1 and _rows(conn, "other-model") == 1


def test_cache_survives_later_rollback(conn):
    embed_cached(conn, FakeEmbedder(), "fake", {text_hash("가"): "가"})
    conn.execute("SELECT 1")
    conn.rollback()                                          # 빌드가 뒤에서 실패해도 캐시는 남는다
    assert _rows(conn, "fake") == 1


def test_embedder_returning_wrong_count_is_an_error(conn):
    class Short(FakeEmbedder):
        def embed(self, texts):
            return []
    with pytest.raises(RuntimeError, match="임베딩 수"):
        embed_cached(conn, Short(), "fake", {text_hash("가"): "가"})
    assert _rows(conn, "fake") == 0


def test_indexes_lists_only_project_indexes(osx):
    assert osx.indexes() == []
    osx.create_index("reg-provisions-r901", 4)
    osx.create_index("reg-provisions-rt9", 4)
    assert osx.indexes() == ["reg-provisions-r901", "reg-provisions-rt9"]


def test_search_on_named_index_without_alias(osx):
    osx.put_pipeline()
    osx.create_index("reg-provisions-r902", 4)
    osx.bulk("reg-provisions-r902", [DOC])
    osx.refresh("reg-provisions-r902")
    assert osx.alias_target() is None
    r = search(osx, FakeEmbedder(), None, "증빙서", rerank=False, index="reg-provisions-r902")
    assert [h["path"] for h in r["hits"]] == ["a27.p1"]


class _Recorder:
    def __init__(self):
        self.seen = []

    def embed(self, texts):
        self.seen += texts
        return [[0.0] * 4 for _ in texts]


def test_long_texts_are_truncated_for_embedding_only(conn):
    """실데이터(2026-10-03): 8,192 토큰을 넘는 청크로 bge-m3가 400을 냈다. 임베딩 입력만 자른다 (BM25 본문은 그대로)."""
    from reg.index.cache import EMBED_MAX_CHARS, embed_cached

    rec = _Recorder()
    embed_cached(conn, rec, "m-trunc", {"h-long": "가" * (EMBED_MAX_CHARS + 500), "h-short": "짧은 조문"})
    assert sorted(len(t) for t in rec.seen) == [len("짧은 조문"), EMBED_MAX_CHARS]
