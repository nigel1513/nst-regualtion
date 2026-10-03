"""서비스 UI 개편 §3 규정 찾기: GET /api/v1/regulations (서버 필터·정렬·페이지·집계)."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from reg.api.app import create_app
from reg.api.regulations import kind_group
from reg.core.effective import Effective
from reg.core.ingest.loader import add_version, rebuild_work, upsert_work
from reg.core.ingest.process import process_once
from reg.core.model import ParsedDoc, Prov
from reg.platform.archive import store as _store
from reg.platform.sniff import FileKind
from reg.platform.storage.blob import LocalBlobStore
from tests.test_api import S
from tests.test_process import seed_alio


def _work(conn, blob, wid: str, title: str, inst_id: int | None, d: date, n_articles: int, salt: int) -> None:
    upsert_work(conn, wid, "INTERNAL_REG", title, inst_id, {})
    sid = _store(conn, blob, source="alio", url="u", content=b"%PDF-r" + bytes([salt]),
                 kind=FileKind("application/pdf", "pdf"), meta={}).id
    provs = [Prov(f"a{i}", "article", f"제{i}조", None, f"본문 {i}") for i in range(1, n_articles + 1)]
    add_version(conn, wid, sid, ParsedDoc(title, None, [], provs), Effective(d, "supplement", "CONFIRMED", d))
    rebuild_work(conn, wid, date(2026, 10, 2))


@pytest.fixture
def api(conn, migrated, tmp_path):
    blob = LocalBlobStore(tmp_path)
    seed_alio(conn, blob, (S / "kasi-yeobi-339.pdf").read_bytes())
    process_once(conn, blob, today=date(2026, 10, 2))
    tid = conn.execute("INSERT INTO regulation.institution (code, name, kind) VALUES ('TST','시험연구원','GRI')"
                       " RETURNING id").fetchone()["id"]
    _work(conn, blob, "kr/reg/TST/회계규정", "회계규정", tid, date(2025, 5, 1), 3, 1)
    _work(conn, blob, "kr/reg/TST/회계처리지침", "회계처리지침", tid, date(2023, 2, 1), 5, 2)
    _work(conn, blob, "kr/reg/TST/물품관리기준", "물품관리기준", tid, date(2022, 1, 1), 1, 3)
    _work(conn, blob, "kr/reg/TST/옛회계요령", "옛회계요령", tid, date(2019, 1, 1), 1, 4)
    conn.execute("UPDATE regulation.work SET status = 'ABOLISHED', abolished_on = '2026-01-01'"
                 " WHERE id = 'kr/reg/TST/옛회계요령'")
    conn.commit()
    with TestClient(create_app(migrated[0], blob)) as c:
        yield c


def test_kind_group_rules():
    assert kind_group("kr/reg/A/여비규정", "여비규정") == "reg"
    assert kind_group("kr/reg/A/x", "회계처리지침") == "guide" and kind_group("kr/reg/A/x", "출장요령") == "guide"
    assert kind_group("kr/reg/A/x", "물품관리기준") == "standard" and kind_group("kr/reg/A/x", "시행세칙") == "standard"
    assert kind_group("kr/law/001", "국가연구개발혁신법") == "law" and kind_group("kr/admrul/9", "고시") == "law"


def test_list_defaults_to_current_with_facets(api):
    d = api.get("/api/v1/regulations").json()
    titles = [x["title"] for x in d["items"]]
    assert d["total"] == 4 and "옛회계요령" not in titles
    it = next(x for x in d["items"] if x["title"] == "회계처리지침")
    assert (it["institution"], it["institution_name"], it["kind"], it["kind_label"]) == ("TST", "시험연구원", "guide", "요령·지침")
    assert it["articles"] == 5 and it["effective_from"] == "2023-02-01" and it["href"].startswith("/regulations/kr/reg/TST/")
    f = d["facets"]
    assert {x["value"]: x["count"] for x in f["institution"]} == {"KASI": 1, "TST": 3}
    assert {x["value"]: x["count"] for x in f["kind"]}["guide"] == 1
    assert {x["value"]: x["count"] for x in f["status"]} == {"current": 4, "abolished": 1}
    assert f["topic"] == [] and d["topics_available"] is False


def test_query_filters_sort_and_relevance(api):
    d = api.get("/api/v1/regulations", params={"q": "회계"}).json()
    assert [x["title"] for x in d["items"]] == ["회계규정", "회계처리지침"]       # 앞부분 일치·짧은 제목 먼저
    d = api.get("/api/v1/regulations", params={"q": "회계", "status": "all"}).json()
    assert d["total"] == 3
    d = api.get("/api/v1/regulations", params=[("inst", "TST"), ("kind", "reg"), ("kind", "guide")]).json()
    assert sorted(x["title"] for x in d["items"]) == ["회계규정", "회계처리지침"]
    assert {x["value"]: x["count"] for x in d["facets"]["kind"]}["standard"] == 1   # 자기 축은 빼고 센다
    d = api.get("/api/v1/regulations", params={"inst": "TST", "sort": "recent"}).json()
    assert [x["title"] for x in d["items"]] == ["회계규정", "회계처리지침", "물품관리기준"]
    d = api.get("/api/v1/regulations", params={"inst": "TST", "sort": "articles"}).json()
    assert d["items"][0]["title"] == "회계처리지침"
    assert api.get("/api/v1/regulations", params={"sort": "bogus"}).status_code == 422


def test_pagination(api):
    d = api.get("/api/v1/regulations", params={"size": 2, "page": 2, "sort": "title"}).json()
    assert (d["total"], d["page"], d["size"], len(d["items"])) == (4, 2, 2, 2)
    assert api.get("/api/v1/regulations", params={"size": 2, "page": 9}).json()["items"] == []


def test_topic_filter_when_table_exists(api, topic_table):
    topic_table([("kr/reg/TST/회계규정", "finance"), ("kr/reg/TST/회계처리지침", "finance"),
                 ("kr/reg/TST/물품관리기준", "contract")])
    d = api.get("/api/v1/regulations", params={"topic": "finance"}).json()
    assert d["topics_available"] is True and sorted(x["title"] for x in d["items"]) == ["회계규정", "회계처리지침"]
    assert d["items"][0]["topics"][0] == {"topic": "finance", "label": "회계·재무"}
    assert {x["value"]: x["count"] for x in d["facets"]["topic"]} == {"finance": 2, "contract": 1}
