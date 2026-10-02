from reg.index.health import embed_ok
from reg.index.indexer import build_release
from reg.index.release import prune_releases
from tests.index.fakes import FakeEmbedder


def _build(conn, os, publish=True):
    return build_release(conn, os, FakeEmbedder(), "fake", publish=publish, force=True)


def test_prune_keeps_published_and_previous(loaded, osx):
    r = [_build(loaded, osx) for _ in range(4)]
    osx.create_index("nais-regulations-rt1", 4)                       # 이 규칙 밖 이름은 건드리지 않는다
    out = prune_releases(loaded, osx)
    assert sorted(out["deleted"]) == sorted([r[0]["index"], r[1]["index"]])
    assert osx.indexes() == sorted([r[2]["index"], r[3]["index"], "nais-regulations-rt1"])
    assert osx.alias_target() == r[3]["index"]


def test_prune_dry_run_deletes_nothing(loaded, osx):
    r = [_build(loaded, osx) for _ in range(3)]
    out = prune_releases(loaded, osx, dry_run=True)
    assert out["deleted"] == [r[0]["index"]] and len(osx.indexes()) == 3


def test_prune_keeps_in_progress_build(loaded, osx):
    r = [_build(loaded, osx) for _ in range(2)]
    waiting = _build(loaded, osx, publish=False)                      # 게이트 대기 중
    prune_releases(loaded, osx)
    assert waiting["index"] in osx.indexes()
    assert {r[0]["index"], r[1]["index"]} <= set(osx.indexes())


def test_prune_marks_stale_build_failed(loaded, osx):
    _build(loaded, osx)
    old = _build(loaded, osx, publish=False)
    loaded.execute("UPDATE ops.release SET created_at = now() - interval '7 hours' WHERE id = %s",
                   (old["release_id"],))
    loaded.commit()
    out = prune_releases(loaded, osx)
    assert old["index"] in out["deleted"] and out["stale_failed"] == [old["release_id"]]
    st = loaded.execute("SELECT state, error FROM ops.release WHERE id = %s", (old["release_id"],)).fetchone()
    assert st["state"] == "FAILED" and st["error"].startswith("stale")


def test_prune_never_deletes_alias_target_even_if_db_disagrees(loaded, osx):
    a = _build(loaded, osx)
    _build(loaded, osx)
    _build(loaded, osx)
    osx.swap_alias(a["index"])                                       # DB와 어긋난 상태(수동 복구 등)
    prune_releases(loaded, osx)
    assert a["index"] in osx.indexes() and osx.alias_target() == a["index"]


def test_embed_ok():
    from reg.platform.llm import ProviderError

    class Down(FakeEmbedder):
        def embed(self, texts):
            raise ProviderError("down")

    class Empty(FakeEmbedder):
        def embed(self, texts):
            return [[]]

    assert embed_ok(FakeEmbedder()) is True
    assert embed_ok(Down()) is False
    assert embed_ok(Empty()) is False
    assert embed_ok(FakeEmbedder(delay=0.2), limit=0.05) is False


def test_prune_does_not_fail_a_release_published_meanwhile(loaded, osx, os_url, migrated):
    from reg.index.os import OpenSearch
    from reg.platform.db.conn import connect

    _build(loaded, osx)
    old = _build(loaded, osx, publish=False)
    loaded.execute("UPDATE ops.release SET created_at = now() - interval '7 hours' WHERE id = %s",
                   (old["release_id"],))
    loaded.commit()

    class PublishedMeanwhile(OpenSearch):
        def alias_target(self):                                       # 정리가 상태를 읽은 직후 다른 태스크가 게시
            with connect(migrated[0]) as c:
                c.execute("UPDATE ops.release SET state = 'PUBLISHED', published_at = now() WHERE id = %s",
                          (old["release_id"],))
                c.commit()
            return super().alias_target()

    prune_releases(loaded, PublishedMeanwhile(os_url))
    st = loaded.execute("SELECT state FROM ops.release WHERE id = %s", (old["release_id"],)).fetchone()
    assert st["state"] == "PUBLISHED" and old["index"] in osx.indexes()
