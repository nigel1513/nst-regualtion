import pytest

from reg.index import indexer
from reg.index.indexer import build_release
from reg.index.os import OpenSearch
from reg.index.release import publish_release
from reg.platform.llm import ProviderError
from tests.index.fakes import FakeEmbedder


def _state(conn, rid):
    return conn.execute("SELECT state FROM ops.release WHERE id = %s", (rid,)).fetchone()["state"]


def test_build_uses_cache_on_second_run(loaded, osx):
    e1 = FakeEmbedder()
    a = build_release(loaded, osx, e1, "fake")
    assert a["chunks"] > 30 and a["embedded"] == a["unique_texts"] == e1.texts
    assert osx.count(a["index"]) == a["chunks"] and osx.alias_target() == a["index"]
    e2 = FakeEmbedder()
    b = build_release(loaded, osx, e2, "fake", force=True)
    assert b["embedded"] == 0 and e2.texts == 0 and b["chunks"] == a["chunks"]
    assert osx.alias_target() == b["index"]


def test_build_streams_in_batches(loaded, osx, monkeypatch):
    monkeypatch.setattr(indexer, "BULK", 10)
    e = FakeEmbedder()
    st = build_release(loaded, osx, e, "fake", publish=False)
    assert e.calls > 1 and e.max_batch <= 10
    assert osx.count(st["index"]) == st["chunks"]
    assert _state(loaded, st["release_id"]) == "BUILDING" and osx.alias_target() is None


def test_gpu_dies_midway_keeps_alias_and_cache(loaded, osx, monkeypatch):
    monkeypatch.setattr(indexer, "BULK", 10)
    before = build_release(loaded, osx, FakeEmbedder(), "fake")["index"]
    with pytest.raises(ProviderError):
        build_release(loaded, osx, FakeEmbedder(fail_after=15), "fake-2")
    assert osx.alias_target() == before
    assert osx.indexes() == [before]                            # 실패한 새 색인은 지워졌다
    cached = loaded.execute("SELECT count(*) AS n FROM ops.embedding_cache WHERE model = 'fake-2'").fetchone()["n"]
    assert 0 < cached <= 15
    retry = FakeEmbedder()
    st = build_release(loaded, osx, retry, "fake-2")
    assert retry.texts == st["unique_texts"] - cached           # 재시도는 나머지만 임베딩
    rows = loaded.execute("SELECT state FROM ops.release ORDER BY id").fetchall()
    assert [r["state"] for r in rows] == ["RETIRED", "FAILED", "PUBLISHED"]


def test_publish_requires_gate(loaded, osx):
    st = build_release(loaded, osx, FakeEmbedder(), "fake", publish=False)
    with pytest.raises(RuntimeError, match="게이트"):
        publish_release(loaded, osx, st["release_id"])
    assert osx.alias_target() is None and _state(loaded, st["release_id"]) == "BUILDING"


class _CommitFailsOnce:
    def __init__(self, conn):
        self._c, self.failed = conn, False

    def __getattr__(self, name):
        return getattr(self._c, name)

    def commit(self):
        if not self.failed:
            self.failed = True
            raise RuntimeError("commit 실패")
        self._c.commit()


def test_db_failure_after_swap_keeps_index_and_restores_alias(loaded, osx):
    a = build_release(loaded, osx, FakeEmbedder(), "fake")
    b = build_release(loaded, osx, FakeEmbedder(), "fake", publish=False, force=True)
    with pytest.raises(RuntimeError, match="commit 실패"):
        publish_release(_CommitFailsOnce(loaded), osx, b["release_id"], require_gate=False)
    assert osx.count(b["index"]) == b["chunks"]                 # 색인은 지우지 않는다 (리뷰 지적 사항)
    assert osx.alias_target() == a["index"]                     # DB와 맞게 이전 색인으로 되돌린다
    assert _state(loaded, a["release_id"]) == "PUBLISHED" and _state(loaded, b["release_id"]) == "BUILDING"
    out = publish_release(loaded, osx, b["release_id"], require_gate=False)
    assert out["previous_index"] == a["index"] and osx.alias_target() == b["index"]


def test_alias_swap_failure_leaves_db_and_index(loaded, osx, os_url):
    class SwapFails(OpenSearch):
        def swap_alias(self, new_index):
            raise RuntimeError("swap 실패")

    a = build_release(loaded, osx, FakeEmbedder(), "fake")
    b = build_release(loaded, osx, FakeEmbedder(), "fake", publish=False, force=True)
    with pytest.raises(RuntimeError, match="swap 실패"):
        publish_release(loaded, SwapFails(os_url), b["release_id"], require_gate=False)
    assert osx.alias_target() == a["index"] and osx.count(b["index"]) == b["chunks"]
    assert _state(loaded, a["release_id"]) == "PUBLISHED" and _state(loaded, b["release_id"]) == "BUILDING"


def test_publish_twice_is_idempotent(loaded, osx):
    a = build_release(loaded, osx, FakeEmbedder(), "fake")
    again = publish_release(loaded, osx, a["release_id"])
    assert again["already"] is True and osx.alias_target() == a["index"]
