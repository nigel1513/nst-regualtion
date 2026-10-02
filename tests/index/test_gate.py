import pytest

from reg.index.indexer import build_release
from reg.index.release import chunk_drop_ok, gate_release, publish_release, smoke_check
from tests.index.fakes import SMOKE_BAD, SMOKE_OK, FakeEmbedder, FakeReranker


def _row(conn, rid):
    return conn.execute("SELECT state, error, stats FROM ops.release WHERE id = %s", (rid,)).fetchone()


def _gate(conn, os, rid, smoke=SMOKE_OK):
    return gate_release(conn, os, FakeEmbedder(), FakeReranker(), rid, smoke)


def test_smoke_check_matches_article_prefix(loaded, osx):
    st = build_release(loaded, osx, FakeEmbedder(), "fake", publish=False)
    ok = smoke_check(osx, FakeEmbedder(), FakeReranker(), st["index"], SMOKE_OK)
    bad = smoke_check(osx, FakeEmbedder(), FakeReranker(), st["index"], SMOKE_BAD)
    assert ok[0]["hit"] is True and ok[0]["mode"] == "hybrid" and len(ok[0]["top"]) <= 5
    assert bad[0]["hit"] is False


def test_gate_passes_then_publish(loaded, osx):
    st = build_release(loaded, osx, FakeEmbedder(), "fake", publish=False)
    g = _gate(loaded, osx, st["release_id"])
    assert g["passed"] is True and g["prev_chunks"] is None and g["reasons"] == []
    row = _row(loaded, st["release_id"])
    assert row["state"] == "BUILDING" and row["stats"]["gate"]["passed"] is True
    assert publish_release(loaded, osx, st["release_id"])["published"] is True


def test_gate_fails_on_smoke_miss_and_blocks_publish(loaded, osx):
    a = build_release(loaded, osx, FakeEmbedder(), "fake")
    b = build_release(loaded, osx, FakeEmbedder(), "fake", publish=False, force=True)
    g = _gate(loaded, osx, b["release_id"], SMOKE_BAD)
    assert g["passed"] is False and any("kasi-a999" in r for r in g["reasons"])
    row = _row(loaded, b["release_id"])
    assert row["state"] == "FAILED" and row["error"].startswith("gate:")
    with pytest.raises(RuntimeError):
        publish_release(loaded, osx, b["release_id"])
    assert osx.alias_target() == a["index"] and osx.count(b["index"]) == b["chunks"]
    with pytest.raises(RuntimeError, match="FAILED"):
        _gate(loaded, osx, b["release_id"])                      # 실패한 release는 다시 빌드해야 한다


def test_chunk_drop_boundary():
    assert chunk_drop_ok(98, 100) is True                        # 정확히 2% 감소는 통과
    assert chunk_drop_ok(97, 100) is False                       # 2% 넘게 줄면 실패
    assert chunk_drop_ok(120, 100) is True                       # 늘어난 것은 문제 아님
    assert chunk_drop_ok(0, None) is True                        # 첫 게시(직전 없음)


def test_gate_fails_on_chunk_drop_over_two_percent(loaded, osx):
    a = build_release(loaded, osx, FakeEmbedder(), "fake")
    loaded.execute("UPDATE ops.release SET stats = stats || %s::jsonb WHERE id = %s",
                   (f'{{"chunks": {a["chunks"] * 2}}}', a["release_id"]))   # 직전이 두 배였다고 둔다(50% 감소)
    loaded.commit()
    b = build_release(loaded, osx, FakeEmbedder(), "fake", publish=False, force=True)
    g = _gate(loaded, osx, b["release_id"])
    assert g["passed"] is False and g["prev_chunks"] == a["chunks"] * 2
    assert any("청크 수" in r for r in g["reasons"])


def test_gate_compares_with_previous_published(loaded, osx):
    a = build_release(loaded, osx, FakeEmbedder(), "fake")
    b = build_release(loaded, osx, FakeEmbedder(), "fake", publish=False, force=True)
    g = _gate(loaded, osx, b["release_id"])
    assert g["passed"] is True and g["prev_chunks"] == a["chunks"] == g["chunks"]


def test_gate_on_published_release_is_noop(loaded, osx):
    a = build_release(loaded, osx, FakeEmbedder(), "fake")
    g = _gate(loaded, osx, a["release_id"], SMOKE_BAD)
    assert g["passed"] is True and g["already_published"] is True


def test_gate_requires_smoke_cases(loaded, osx):
    st = build_release(loaded, osx, FakeEmbedder(), "fake", publish=False)
    with pytest.raises(ValueError):
        _gate(loaded, osx, st["release_id"], [])


def test_gate_with_embedder_down_does_not_fail_the_release(loaded, osx):
    from reg.platform.llm import ProviderError

    class Down(FakeEmbedder):
        def embed(self, texts):
            raise ProviderError("down")

    st = build_release(loaded, osx, FakeEmbedder(), "fake", publish=False)
    with pytest.raises(ProviderError):
        gate_release(loaded, osx, Down(), FakeReranker(), st["release_id"], SMOKE_OK)
    assert _row(loaded, st["release_id"])["state"] == "BUILDING"     # GPU가 돌아오면 같은 release로 다시 본다


def test_gate_with_reranker_down_does_not_fail_the_release(loaded, osx):
    from reg.platform.llm import ProviderError

    class Down(FakeReranker):
        def rerank(self, q, docs):
            raise ProviderError("down")

    st = build_release(loaded, osx, FakeEmbedder(), "fake", publish=False)
    with pytest.raises(ProviderError):
        gate_release(loaded, osx, FakeEmbedder(), Down(), st["release_id"], SMOKE_OK)
    assert _row(loaded, st["release_id"])["state"] == "BUILDING"
