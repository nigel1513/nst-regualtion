from datetime import date

from reg.index.indexer import build_release, doc_state, fingerprint
from reg.index.service import search
from tests.index.fakes import FakeEmbedder


def _v(state="CURRENT", to=None, status="ACTIVE", ab=None):
    return {"version_state": state, "effective_to": to, "work_status": status, "abolished_on": ab}


def test_doc_state_rules():
    assert doc_state(_v()) == ("CURRENT", None)
    assert doc_state(_v(status="ABOLISHED_CANDIDATE")) == ("CURRENT", None)             # 후보는 계속 검색된다
    assert doc_state(_v(status="ABOLISHED", ab=date(2026, 6, 1))) == ("ABOLISHED", date(2026, 6, 1))
    assert doc_state(_v("FUTURE", status="ABOLISHED", ab=date(2026, 6, 1))) == ("ABOLISHED", date(2026, 6, 1))
    assert doc_state(_v("HISTORICAL", date(2020, 1, 1), "ABOLISHED", date(2026, 6, 1))) == ("HISTORICAL", date(2020, 1, 1))
    assert doc_state(_v(status="ABOLISHED")) == ("ABOLISHED", None)                     # 폐지일 모름: 현행에서만 뺀다


def _count(conn):
    return conn.execute("SELECT count(*) AS n FROM ops.release").fetchone()["n"]


def test_unchanged_day_is_skipped(loaded, osx):
    a = build_release(loaded, osx, FakeEmbedder(), "fake")
    e = FakeEmbedder()
    b = build_release(loaded, osx, e, "fake")
    assert b == {"skipped": True, "release_id": a["release_id"], "index": a["index"], "fingerprint": a["fingerprint"]}
    assert _count(loaded) == 1 and e.texts == 0
    assert build_release(loaded, osx, FakeEmbedder(), "fake", force=True)["skipped"] is False


def test_status_only_change_rebuilds(loaded, osx):
    a = build_release(loaded, osx, FakeEmbedder(), "fake")
    loaded.execute("UPDATE regulation.work SET status = 'ABOLISHED', abolished_on = '2026-06-01'")
    loaded.commit()
    b = build_release(loaded, osx, FakeEmbedder(), "fake")
    assert b["skipped"] is False and b["release_id"] != a["release_id"] and b["abolished"] == 1


def test_unpublished_build_is_not_a_baseline(loaded, osx):
    build_release(loaded, osx, FakeEmbedder(), "fake", publish=False)
    assert build_release(loaded, osx, FakeEmbedder(), "fake", publish=False)["skipped"] is False


def test_fingerprint_inputs(loaded):
    f = fingerprint(loaded, "fake")
    assert len(f) == 64 and f == fingerprint(loaded, "fake")
    assert fingerprint(loaded, "other") != f
    loaded.execute("UPDATE regulation.work_version SET effective_to = '2030-01-01' WHERE version_state = 'CURRENT'")
    assert fingerprint(loaded, "fake") != f
    loaded.rollback()


def test_abolished_hidden_from_current_but_found_as_of_before(loaded, osx):
    loaded.execute("UPDATE regulation.work SET status = 'ABOLISHED', abolished_on = '2026-06-01'")
    loaded.commit()
    build_release(loaded, osx, FakeEmbedder(), "fake")
    e = FakeEmbedder()
    assert search(osx, e, None, "증빙서", rerank=False)["hits"] == []
    assert search(osx, e, None, "증빙서", as_of="2025-01-01", rerank=False)["hits"]
    assert search(osx, e, None, "증빙서", as_of="2026-07-01", rerank=False)["hits"] == []


def test_abolished_candidate_stays_searchable(loaded, osx):
    loaded.execute("UPDATE regulation.work SET status = 'ABOLISHED_CANDIDATE'")
    loaded.commit()
    build_release(loaded, osx, FakeEmbedder(), "fake")
    assert search(osx, FakeEmbedder(), None, "증빙서", rerank=False)["hits"]
