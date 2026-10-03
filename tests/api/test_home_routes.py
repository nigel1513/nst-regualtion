"""서비스 UI 개편 §2 홈: GET /api/v1/home (기관 머리 수치, 최근 바뀐 규정과 바뀐 조문 요약, 주제 수, 전체 기관 현황)."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from reg.api.app import create_app
from reg.api.home import summarize_changes
from reg.core.effective import Effective
from reg.core.ingest.loader import add_version, rebuild_work, upsert_work
from reg.core.ingest.process import process_once
from reg.core.model import ParsedDoc, Prov
from reg.platform.archive import store as _store
from reg.platform.sniff import FileKind
from reg.platform.storage.blob import LocalBlobStore
from tests.test_api import S
from tests.test_process import seed_alio

TWID = "kr/reg/TST/출장규정"


def _two_versions(conn, blob, inst_id: int) -> list[str]:
    upsert_work(conn, TWID, "INTERNAL_REG", "출장규정", inst_id, {})
    ids = []
    v1 = [Prov("a1", "article", "제1조", "목적", "이 규정은 출장에 관한 사항을 정한다."),
          Prov("a2", "article", "제2조", "증빙", ""),
          Prov("a2.p1", "paragraph", "①", None, "출장 후 3일 이내에 증빙서를 제출한다.", parent="a2"),
          Prov("a3", "article", "제3조", "폐지될 조", "없어질 조문")]
    v2 = [Prov("a1", "article", "제1조", "목적", "이 규정은 출장에 관한 사항을 정한다."),
          Prov("a2", "article", "제2조", "증빙", ""),
          Prov("a2.p1", "paragraph", "①", None, "출장 후 7일 이내에 증빙서를 제출한다.", parent="a2"),
          Prov("a4", "article", "제4조", "새 조", "새로 생긴 조문")]
    for i, (d, provs) in enumerate([(date(2020, 1, 1), v1), (date(2025, 3, 1), v2)]):
        sid = _store(conn, blob, source="alio", url="u", content=b"%PDF-h" + bytes([i]),
                     kind=FileKind("application/pdf", "pdf"), meta={}).id
        ids.append(add_version(conn, TWID, sid, ParsedDoc("출장규정", None, [], provs),
                               Effective(d, "supplement", "CONFIRMED", d)))
    rebuild_work(conn, TWID, date(2026, 10, 2))
    return ids


@pytest.fixture
def api(conn, migrated, tmp_path):
    blob = LocalBlobStore(tmp_path)
    seed_alio(conn, blob, (S / "kasi-yeobi-339.pdf").read_bytes())
    process_once(conn, blob, today=date(2026, 10, 2))
    tid = conn.execute("INSERT INTO regulation.institution (code, name, kind) VALUES ('TST','시험연구원','GRI')"
                       " RETURNING id").fetchone()["id"]
    conn.execute("INSERT INTO regulation.institution (code, name, kind) VALUES ('EMP','빈연구원','GRI')")
    ids = _two_versions(conn, blob, tid)
    conn.execute("INSERT INTO regulation.review_task (kind, target, work_id) VALUES ('PARSE', %s, %s)", (ids[1], TWID))
    conn.commit()
    with TestClient(create_app(migrated[0], blob)) as c:
        yield c


def test_home_for_institution_has_header_and_recent_changes(api):
    r = api.get("/api/v1/home", params={"inst": "TST"})
    assert r.status_code == 200
    d = r.json()
    h = d["institution"]
    assert (h["code"], h["name"], h["current_works"], h["versions"], h["open_reviews"]) == ("TST", "시험연구원", 1, 2, 1)
    assert h["last_amended"] == "2025-03-01" and h["last_fetched"]
    assert d["institutions"] is None
    rec = d["recent"][0]
    assert rec["work_id"] == TWID and rec["title"] == "출장규정" and rec["effective_from"] == "2025-03-01"
    assert rec["kind_label"] == "개정" and rec["href"].startswith("/regulations/kr/reg/TST/")
    arts = {a["label"]: a for a in rec["changes"]["articles"]}
    assert arts["제2조"]["kind"] == "MODIFIED" and arts["제2조"]["detail"] == "3일 → 7일"
    assert arts["제4조"]["kind"] == "ADDED" and arts["제3조"]["kind"] == "DELETED"
    assert "제1조" not in arts
    assert rec["changes"]["text"].startswith("제2조 증빙 3일 → 7일")


def test_home_first_version_is_enactment_without_changes(api):
    rec = api.get("/api/v1/home", params={"inst": "KASI"}).json()["recent"][0]
    assert rec["title"] == "여비규정" and rec["changes"]["articles"] == []
    assert rec["kind_label"] in ("제정", "개정", "전부개정")


def test_home_all_lists_institution_table(api):
    d = api.get("/api/v1/home").json()
    assert d["institution"] is None and d["recent"] == []
    rows = {r["code"]: r for r in d["institutions"]}
    assert rows["TST"]["current_works"] == 1 and rows["TST"]["open_reviews"] == 1 and rows["TST"]["versions"] == 2
    assert rows["KASI"]["current_works"] == 1 and rows["EMP"]["current_works"] == 0 and rows["EMP"]["last_amended"] is None
    assert d["totals"]["current_works"] == 2 and d["totals"]["institutions"] == 2


def test_home_topics_omitted_without_topic_table_and_unknown_inst_404(api):
    assert api.get("/api/v1/home", params={"inst": "TST"}).json()["topics"] is None
    assert api.get("/api/v1/home", params={"inst": "NOPE"}).status_code == 404


def test_home_topics_counted_when_topic_table_exists(api, topic_table):
    topic_table([(TWID, "travel")])
    t = api.get("/api/v1/home", params={"inst": "TST"}).json()["topics"]
    assert t == [{"topic": "travel", "label": "여비·출장", "count": 1}]


def test_summarize_changes_falls_back_to_article_list():
    rows = [{"kind": "MODIFIED", "path": f"a{i}", "unit": "article", "from_text": "가", "to_text": "나",
             "label": f"제{i}조", "heading": None, "ord": i} for i in range(1, 6)]
    s = summarize_changes(rows, limit=3)
    assert [a["label"] for a in s["articles"]] == ["제1조", "제2조", "제3조"] and s["more"] == 2
    assert s["text"] == "제1조 개정 · 제2조 개정 · 제3조 개정 외 2건"
    assert summarize_changes([], limit=3) == {"articles": [], "more": 0, "text": ""}
