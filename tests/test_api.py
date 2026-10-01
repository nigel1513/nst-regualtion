from datetime import date
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from reg.api.app import create_app
from reg.process import process_once
from reg.storage.blob import LocalBlobStore
from tests.test_process import seed_alio
from reg.collect.archive import store as _store
from reg.collect.sniff import FileKind
from reg.load.loader import add_version, rebuild_work, upsert_work
from reg.structure.effective import Effective
from reg.structure.model import ParsedDoc, Prov

S = Path(__file__).parent / "fixtures" / "samples"
WID = "kr/reg/KASI/여비규정"


@pytest.fixture
def api(conn, migrated, tmp_path):
    blob = LocalBlobStore(tmp_path)
    seed_alio(conn, blob, (S / "kasi-yeobi-339.pdf").read_bytes())
    process_once(conn, blob, today=date(2026, 10, 2))
    with TestClient(create_app(migrated[0], blob)) as c:
        yield c


def test_institutions_and_works(api):
    inst = api.get("/api/v1/institutions").json()
    assert {"code": "KASI", "name": "한국천문연구원", "kind": "GRI", "works": 1} in inst
    works = api.get("/api/v1/works", params={"institution": "KASI"}).json()
    assert works[0]["id"] == WID and works[0]["version"]["effective_from"] == "2024-01-17"
    assert api.get("/api/v1/works", params={"q": "여비"}).json()[0]["id"] == WID


def test_view_current_with_refs_and_unicode_id(api):
    r = api.get(f"/api/v1/work/view?id={quote(WID, safe='')}")
    assert r.status_code == 200
    v = r.json()
    assert v["work"]["title"] == "여비규정" and v["version"]["version_state"] == "CURRENT"
    p = {x["path"]: x for x in v["provisions"]}
    assert "7일 이내에" in p["a27.p1"]["text"] and p["a27"]["anchor"]["page"] == 12
    refs = v["refs"][str(p["a27.p3"]["id"])]
    assert any(x["rel_type"] == "EXCEPTION" and x["target_path"] == "a27.p1" for x in refs)
    assert v["history"][-1]["number"] == "339" and v["version"]["source"]["has_view"] is True


def test_as_of_before_first_version_is_404(api):
    r = api.get("/api/v1/work/view", params={"id": WID, "as_of": "1990-01-01"})
    assert r.status_code == 404 and "시행 중인 버전이 없습니다" in r.json()["detail"]


def test_versions_and_files(api):
    vs = api.get("/api/v1/work/versions", params={"id": WID}).json()
    assert vs[0]["effective_from"] == "2024-01-17"
    f = api.get("/api/v1/file", params={"version": vs[0]["id"], "kind": "view"})
    assert f.status_code == 200 and f.content.startswith(b"%PDF") and f.headers["content-type"] == "application/pdf"
    o = api.get("/api/v1/file", params={"version": vs[0]["id"], "kind": "original"})
    assert "filename*=UTF-8''" in o.headers["content-disposition"]


def test_unknown_work_404(api):
    assert api.get("/api/v1/work/view", params={"id": "kr/reg/NONE/x"}).status_code == 404


def test_references_incoming_and_outgoing(api):
    v = api.get("/api/v1/work/view", params={"id": WID}).json()
    p = {x["path"]: x for x in v["provisions"]}
    r = api.get("/api/v1/references", params={"pv": p["a27.p1"]["id"]}).json()
    assert any(x["source_path"] == "a27.p3" and x["rel_type"] == "EXCEPTION" for x in r["incoming"])
    out = api.get("/api/v1/references", params={"pv": p["a29"]["id"]}).json()["outgoing"]
    assert {x["target_name"] for x in out} >= {"공무원 여비규정"}


def test_diff_between_versions(conn, migrated, tmp_path):
    blob = LocalBlobStore(tmp_path)
    upsert_work(conn, "kr/reg/T/규정", "INTERNAL_REG", "규정", None, {})
    ids = []
    for i, (d, provs) in enumerate([(date(2020, 1, 1), [Prov("a1", "article", "제1조", "목적", "옛 본문입니다")]),
                                    (date(2024, 1, 1), [Prov("a1", "article", "제1조", "목적", "새 본문입니다"),
                                                        Prov("a2", "article", "제2조", "정의", "추가된 조문")])]):
        sid = _store(conn, blob, source="alio", url="u", content=b"%PDF" + bytes([i]),
                     kind=FileKind("application/pdf", "pdf"), meta={}).id
        ids.append(add_version(conn, "kr/reg/T/규정", sid, ParsedDoc("규정", None, [], provs),
                               Effective(d, "supplement", "CONFIRMED", d)))
    rebuild_work(conn, "kr/reg/T/규정", date(2026, 10, 2))
    conn.commit()
    with TestClient(create_app(migrated[0], blob)) as c:
        d = c.get("/api/v1/diff", params={"from": ids[0], "to": ids[1]}).json()
        assert sorted((x["kind"], x["path"]) for x in d["changes"]) == [("ADDED", "a2"), ("MODIFIED", "a1")]
        assert c.get("/api/v1/diff", params={"from": ids[0], "to": "nope"}).status_code == 404


def test_search_escapes_wildcards(api):
    hits = api.get("/api/v1/search", params={"q": "7일 이내"}).json()
    assert any(h["path"] == "a27.p1" and "7일 이내" in h["snippet"] for h in hits)
    assert api.get("/api/v1/search", params={"q": "%%"}).json() == []
    assert api.get("/api/v1/search", params={"q": "a"}).status_code == 422


def test_review_tasks_list(api):
    rows = api.get("/api/v1/review-tasks", params={"status": "OPEN"}).json()
    assert isinstance(rows, list) and all(r["status"] == "OPEN" for r in rows)


def test_references_for_article_subtree(api):
    v = api.get("/api/v1/work/view", params={"id": WID}).json()
    ids = sorted((x["id"] for x in v["provisions"] if x["path"] == "a27" or x["path"].startswith("a27.")),
                 key=lambda i: next(x["path"] for x in v["provisions"] if x["id"] == i) != "a27.p3")  # ③항을 맨 앞에
    r = api.get("/api/v1/references", params=[("pv", i) for i in ids]).json()
    assert any(x["target_path"] == "a13" for x in r["outgoing"])  # ③항의 '제13조'가 조 단위 패널에 보인다
