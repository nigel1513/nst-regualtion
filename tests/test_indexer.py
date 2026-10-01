from datetime import date

import pytest

from reg.process import process_once
from reg.search.indexer import build_release
from reg.search.os import OpenSearch
from reg.storage.blob import LocalBlobStore
from tests.test_process import FX, seed_alio


class FakeEmbedder:
    def __init__(self, fail=False):
        self.fail, self.calls, self.dim = fail, 0, 4

    def embed(self, texts):
        if self.fail:
            from reg.llm import ProviderError
            raise ProviderError("down")
        self.calls += len(texts)
        return [[float(len(t) % 7), 1.0, 0.5, 0.25] for t in texts]


@pytest.fixture
def loaded(conn, tmp_path):
    blob = LocalBlobStore(tmp_path)
    seed_alio(conn, blob, (FX / "samples" / "kasi-yeobi-339.pdf").read_bytes())
    process_once(conn, blob, today=date(2026, 10, 2))
    return conn


def test_build_and_publish(loaded, os_url):
    os = OpenSearch(os_url)
    for name in [os.alias_target()] if os.alias_target() else []:
        os.delete_index(name)
    st = build_release(loaded, os, FakeEmbedder(), "fake")
    assert st["chunks"] > 30 and os.alias_target() == st["index"]
    assert os.count(st["index"]) == st["chunks"]
    r = loaded.execute("SELECT state FROM regulation.release WHERE id = %s", (st["release_id"],)).fetchone()
    assert r["state"] == "PUBLISHED"
    st2 = build_release(loaded, os, FakeEmbedder(), "fake")
    assert os.alias_target() == st2["index"]
    states = [x["state"] for x in loaded.execute("SELECT state FROM regulation.release ORDER BY id").fetchall()]
    assert states[-2:] == ["RETIRED", "PUBLISHED"]


def test_failed_build_keeps_alias(loaded, os_url):
    os = OpenSearch(os_url)
    before = build_release(loaded, os, FakeEmbedder(), "fake")["index"]
    with pytest.raises(Exception):
        build_release(loaded, os, FakeEmbedder(fail=True), "fake")
    assert os.alias_target() == before
    assert loaded.execute("SELECT state FROM regulation.release ORDER BY id DESC LIMIT 1").fetchone()["state"] == "FAILED"
