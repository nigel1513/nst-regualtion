"""ops.release에는 옛 nais-regulations 줄과 새 reg-provisions 줄이 함께 있다: 게시·게이트·정리·변화 없음 판단은 자기 줄만 본다."""
from reg.index.indexer import build_release
from reg.index.release import gate_release, prune_releases
from tests.index.fakes import SMOKE_OK, FakeEmbedder, FakeReranker


def _old_line(conn):
    conn.execute("INSERT INTO ops.release (state, os_index, embedding_model, stats, published_at)"
                 " VALUES ('PUBLISHED', 'nais-regulations-r1', 'fake', '{\"chunks\": 99999999, \"fingerprint\": \"x\"}',"
                 " now() + interval '1 hour')")
    conn.commit()


def _state(conn, index):
    return conn.execute("SELECT state FROM ops.release WHERE os_index = %s", (index,)).fetchone()["state"]


def test_release_lines_are_scoped(loaded, osx):
    _old_line(loaded)
    st = build_release(loaded, osx, FakeEmbedder(), "fake", publish=False)
    g = gate_release(loaded, osx, FakeEmbedder(), FakeReranker(), st["release_id"], SMOKE_OK)
    assert g["passed"] and g["prev_chunks"] is None            # 옛 줄의 청크 수와 비교하지 않는다
    build_release(loaded, osx, FakeEmbedder(), "fake", force=True)
    assert _state(loaded, "nais-regulations-r1") == "PUBLISHED"  # 새 줄 게시가 옛 줄을 내리지 않는다
    assert build_release(loaded, osx, FakeEmbedder(), "fake")["skipped"] is True   # 자기 줄 게시본과 지문 비교
    out = prune_releases(loaded, osx, dry_run=True)
    assert "nais-regulations-r1" not in out["kept"]


def test_build_stats_count_docs_and_vectors(loaded, osx):
    st = build_release(loaded, osx, FakeEmbedder(), "fake")
    assert st["index"].startswith("reg-provisions-r") and st["docs"] == st["chunks"] == osx.count(st["index"])
    assert 0 < st["vectors"] < st["docs"] and st["seconds"] >= 0
    units = osx.search({"size": 0, "aggs": {"u": {"terms": {"field": "unit"}}}}, index=st["index"])
    got = {b["key"] for b in units["aggregations"]["u"]["buckets"]}
    assert {"article", "paragraph", "item"} <= got and "chapter" not in got
    vec = osx.search({"size": 0, "query": {"exists": {"field": "embedding"}},
                      "aggs": {"u": {"terms": {"field": "unit"}}, "s": {"terms": {"field": "version_state"}}}},
                     index=st["index"])["aggregations"]
    assert {b["key"] for b in vec["u"]["buckets"]} <= {"article", "paragraph", "annex"}
    assert {b["key"] for b in vec["s"]["buckets"]} == {"CURRENT"}
