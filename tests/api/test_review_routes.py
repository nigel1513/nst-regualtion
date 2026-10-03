"""검수 작업 API (서비스 UI 스펙 §6): 보강 목록·필터·집계·처리."""
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from reg.api.app import create_app
from reg.core.effective import Effective
from reg.core.ingest.loader import add_version, rebuild_work, upsert_work
from reg.core.model import ParsedDoc, Prov
from reg.platform.archive import store
from reg.platform.sniff import FileKind
from reg.platform.storage.blob import LocalBlobStore

WID = "kr/reg/KASI/여비규정"
A13P2 = "출장자는 「근로기준법」 제74조와 인사규정 제5조에 따라 휴가를 쓴다."
SUPP = "이 규정은 2024년 1월 17일부터 시행한다."


def _doc(conn, blob, content: bytes) -> int:
    return store(conn, blob, source="alio", url="u", content=content, kind=FileKind("application/pdf", "pdf"),
                 meta={}).id


def _task(conn, kind, target, detail, work_id=WID, created="2026-10-01"):
    return conn.execute("INSERT INTO regulation.review_task (kind, target, work_id, detail, created_at)"
                        " VALUES (%s,%s,%s,%s,%s) RETURNING id",
                        (kind, target, work_id, json.dumps(detail, ensure_ascii=False), created)).fetchone()["id"]


@pytest.fixture
def seeded(conn, migrated, tmp_path):
    blob = LocalBlobStore(tmp_path)
    inst = conn.execute("INSERT INTO regulation.institution (code, name, kind) VALUES ('KASI', '한국천문연구원', 'GRI')"
                        " RETURNING id").fetchone()["id"]
    conn.execute("INSERT INTO regulation.institution (code, name, kind) VALUES ('KIST', '한국과학기술연구원', 'GRI')")
    conn.execute("INSERT INTO regulation.alio_rule (seq, institution_id, title, detail) VALUES"
                 " ('100', %s, '여비규정', '{\"jidtDptm\": \"A1747\"}'), ('200', %s, '로고사용기준', '{\"jidtDptm\": \"A1747\"}')",
                 (inst, inst))
    sid = _doc(conn, blob, b"%PDF-1")
    conn.execute("UPDATE regulation.source_document SET view_blob_key = blob_key WHERE id = %s", (sid,))
    upsert_work(conn, WID, "INTERNAL_REG", "여비규정", inst, {"alio_seq": "100"})
    doc = ParsedDoc("여비규정", None, [], [
        Prov("a13", "article", "제13조", "휴가", ""),
        Prov("a13.p2", "paragraph", "②", None, A13P2, parent="a13"),
        Prov("supp@2024-01-17", "supplement", "부칙", None, SUPP),
    ])
    vid = add_version(conn, WID, sid, doc, Effective(date(2024, 1, 17), "supplement", "CONFLICT", None))
    rebuild_work(conn, WID, date(2026, 10, 2))
    low = _doc(conn, blob, b"%PDF-2")
    conn.execute("INSERT INTO regulation.alio_rule_file (file_no, seq, file_name, ord, status, source_document_id)"
                 " VALUES ('9', '200', '로고.pdf', 0, 'fetched', %s)", (low,))
    span = A13P2.index("인사규정")
    ids = {
        "ref": _task(conn, "REFERENCE", f"ref:{WID}:a13.p2:{span}:인사규정",
                     {"name": "인사규정", "path": "a13.p2", "evidence": "인사규정 제5조"}, created="2026-10-03"),
        "law": _task(conn, "REFERENCE", f"ref:{WID}:a13.p2:{A13P2.index('「')}:근로기준법",
                     {"name": "근로기준법", "path": "a13.p2", "evidence": "「근로기준법」 제74조"}),
        "parse": _task(conn, "PARSE", vid, {"check": "gap", "missing": [37]}, created="2026-10-02"),
        "conflict": _task(conn, "CONFLICT", vid, {"basis": "supplement"}),
        "low": _task(conn, "LOW_TEXT", f"source:{low}", {"ocr": "not_needed", "reason": "제N조 조문 형식이 아님"},
                     work_id=None),
    }
    conn.commit()
    with TestClient(create_app(migrated[0], blob)) as c:
        yield c, ids, vid, conn


def _items(api, **params):
    r = api.get("/api/v1/review-tasks", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_list_enriched_reference(seeded):
    api, ids, vid, _ = seeded
    body = _items(api)
    t = next(x for x in body["items"] if x["id"] == ids["ref"])
    # 옛 필드
    assert {"id", "kind", "target", "work_id", "work_title", "detail", "status", "created_at"} <= set(t)
    assert t["institution"] == {"code": "KASI", "name": "한국천문연구원"}
    assert t["work"] == {"id": WID, "title": "여비규정"}
    assert t["version"] == {"id": vid, "effective_from": "2024-01-17", "state": "CURRENT"}
    assert t["location"] == {"label": "제13조 제2항", "path": "a13.p2"}
    s, e = t["excerpt"]["highlight"]
    assert t["excerpt"]["text"][s:e] == "인사규정 제5조"
    assert "인사규정" in t["problem"] and t["todo"] and t["law_pending"] is False
    assert t["department"] == {"code": "A1747", "name": "우주항공청", "scope": "주무부처"}
    assert t["assignee"] is None and t["kind_label"] == "참조 미연결"
    assert t["links"]["viewer"].startswith("/regulations/kr/reg/KASI/%EC%97%AC") and t["links"]["viewer"].endswith(
        "?a=a13#a13.p2")
    assert t["links"]["pdf"].endswith("&kind=view") and "/source/kr/reg/KASI/" in t["links"]["source"]


def test_law_pending_is_grouped_out_by_default(seeded):
    api, ids, *_ = seeded
    body = _items(api)
    got = {x["id"] for x in body["items"]}
    assert ids["law"] not in got and {ids["ref"], ids["parse"], ids["conflict"], ids["low"]} <= got
    assert body["total"] == 4
    pend = _items(api, group="law_pending")
    assert [x["id"] for x in pend["items"]] == [ids["law"]] and pend["items"][0]["law_pending"] is True
    assert "적재" in pend["items"][0]["problem"]
    assert _items(api, group="all")["total"] == 5


def test_summary(seeded):
    api, ids, *_ = seeded
    api.post(f"/api/v1/review-tasks/{ids['parse']}/assign", json={"assignee": "김검수"})
    api.post(f"/api/v1/review-tasks/{ids['conflict']}/hold", json={})
    s = _items(api)["summary"]
    assert s == {"open": 3, "hold": 1, "unassigned": 2, "law_pending": 1,
                 "by_kind": {"REFERENCE": 1, "PARSE": 1, "LOW_TEXT": 1}, "by_institution": {"KASI": 3}}


def test_version_and_source_level_rows(seeded):
    api, ids, _, _ = seeded
    items = {x["id"]: x for x in _items(api)["items"]}
    p = items[ids["parse"]]
    assert p["location"] == {"label": "제37조", "path": None} and "제37조" in p["problem"] and p["excerpt"] is None
    c = items[ids["conflict"]]
    assert c["location"]["label"] == "부칙" and c["excerpt"]["text"] == SUPP
    s, e = c["excerpt"]["highlight"]
    assert c["excerpt"]["text"][s:e] == "2024년 1월 17일"
    low = items[ids["low"]]  # work_id 없음: ALIO 파일 → seq 200 → 기관·제목
    assert low["institution"]["code"] == "KASI" and low["work_title"] == "로고사용기준" and low["work"] is None
    assert low["location"]["label"] == "전체" and low["links"]["viewer"] is None and "조문 형식" in low["problem"]


def test_filters_and_pagination(seeded):
    api, ids, *_ = seeded
    assert {x["id"] for x in _items(api, kind=["PARSE", "CONFLICT"])["items"]} == {ids["parse"], ids["conflict"]}
    assert _items(api, inst="KIST")["total"] == 0
    assert _items(api, inst=["KIST", "KASI"])["total"] == 4
    assert {x["id"] for x in _items(api, q="인사규정")["items"]} == {ids["ref"]}
    assert _items(api, q="여비")["total"] == 3          # 제목
    assert _items(api, q="%")["total"] == 0
    api.post(f"/api/v1/review-tasks/{ids['ref']}/assign", json={"assignee": "김검수"})
    assert [x["id"] for x in _items(api, assignee="김검수")["items"]] == [ids["ref"]]
    assert _items(api, assignee="none")["total"] == 3
    p1, p2 = _items(api, size=3, page=1), _items(api, size=3, page=2)
    assert len(p1["items"]) == 3 and len(p2["items"]) == 1 and p2["total"] == 4
    assert p1["items"][0]["id"] == ids["ref"]               # 최신 생성 먼저
    assert _items(api, page=9)["items"] == [] and _items(api, page=9)["total"] == 4
    assert api.get("/api/v1/review-tasks", params={"size": 101}).status_code == 422
    assert api.get("/api/v1/review-tasks", params={"status": "NOPE"}).status_code == 422
    assert _items(api, summary=False)["summary"] is None


def test_resolve_records_who_when_note(seeded):
    api, ids, _, conn = seeded
    r = api.post(f"/api/v1/review-tasks/{ids['ref']}/resolve",
                 json={"decision": {"target_work_id": "kr/reg/KASI/인사규정"}, "note": "확인", "by": "김검수"})
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["status"] == "RESOLVED" and t["resolved_at"]
    d = t["decision"]
    assert (d["action"], d["by"], d["note"], d["value"]) == ("resolve", "김검수", "확인",
                                                            {"target_work_id": "kr/reg/KASI/인사규정"})
    assert d["at"]
    assert _items(api, status="RESOLVED")["items"][0]["id"] == ids["ref"]
    # 닫힌 작업은 다시 처리하지 못한다
    assert api.post(f"/api/v1/review-tasks/{ids['ref']}/dismiss", json={"reason": "x"}).status_code == 409
    assert api.post(f"/api/v1/review-tasks/{ids['ref']}/assign", json={"assignee": "a"}).status_code == 409
    row = conn.execute("SELECT status, decision FROM regulation.review_decision WHERE target = %s",
                       (t["target"],)).fetchone()
    conn.commit()
    assert row["status"] == "RESOLVED" and row["decision"]["by"] == "김검수"


def test_dismiss_needs_reason_and_uses_assignee_as_actor(seeded):
    api, ids, *_ = seeded
    assert api.post(f"/api/v1/review-tasks/{ids['low']}/dismiss", json={"reason": "  "}).status_code == 422
    assert api.post(f"/api/v1/review-tasks/{ids['low']}/dismiss", json={}).status_code == 422
    api.post(f"/api/v1/review-tasks/{ids['low']}/assign", json={"assignee": "이담당"})
    t = api.post(f"/api/v1/review-tasks/{ids['low']}/dismiss", json={"reason": "목차형 기준이라 정상"}).json()
    assert t["status"] == "DISMISSED" and t["decision"]["by"] == "이담당"
    assert t["decision"]["reason"] == "목차형 기준이라 정상"


def test_hold_and_reopen(seeded):
    api, ids, *_ = seeded
    t = api.post(f"/api/v1/review-tasks/{ids['parse']}/hold", json={"note": "재처리 요청"}).json()
    assert t["status"] == "HOLD" and t["decision"]["note"] == "재처리 요청" and t["resolved_at"] is None
    assert api.post(f"/api/v1/review-tasks/{ids['parse']}/hold").status_code == 409
    assert _items(api, status="HOLD")["total"] == 1
    # 보류 중에도 담당 지정·해결 가능
    assert api.post(f"/api/v1/review-tasks/{ids['parse']}/assign", json={"assignee": "박"}).json()["assignee"] == "박"
    t = api.post(f"/api/v1/review-tasks/{ids['parse']}/reopen").json()
    assert t["status"] == "OPEN" and t["assignee"] == "박"
    assert api.post(f"/api/v1/review-tasks/{ids['parse']}/reopen").status_code == 409


def test_auto_closed_task_cannot_be_reopened(seeded):
    api, ids, _, conn = seeded
    conn.execute("UPDATE regulation.review_task SET status = 'RESOLVED', resolved_at = now() WHERE id = %s",
                 (ids["conflict"],))
    conn.commit()
    assert api.post(f"/api/v1/review-tasks/{ids['conflict']}/reopen").status_code == 409


def test_assign_unassign_and_404(seeded):
    api, ids, *_ = seeded
    assert api.post(f"/api/v1/review-tasks/{ids['ref']}/assign", json={"assignee": " 김 "}).json()["assignee"] == "김"
    assert api.post(f"/api/v1/review-tasks/{ids['ref']}/assign", json={"assignee": None}).json()["assignee"] is None
    assert api.post("/api/v1/review-tasks/999999/assign", json={"assignee": "a"}).status_code == 404
    assert api.post("/api/v1/review-tasks/999999/resolve", json={"decision": {}}).status_code == 404
    assert api.get("/api/v1/review-tasks/999999").status_code == 404
    assert api.get(f"/api/v1/review-tasks/{ids['ref']}").json()["id"] == ids["ref"]


def test_bulk_assign(seeded):
    api, ids, *_ = seeded
    api.post(f"/api/v1/review-tasks/{ids['low']}/dismiss", json={"reason": "정상"})
    r = api.post("/api/v1/review-tasks/bulk-assign",
                 json={"ids": [ids["ref"], ids["parse"], ids["low"], 999999], "assignee": "최"}).json()
    assert r == {"updated": sorted([ids["ref"], ids["parse"]]), "skipped": sorted([ids["low"], 999999])}
    assert _items(api, assignee="최")["total"] == 2
    assert api.post("/api/v1/review-tasks/bulk-assign", json={"ids": [], "assignee": "a"}).status_code == 422


def test_decisions_survive_regeneration(seeded):
    """reg process --rebuild는 review_task를 비우고 다시 만든다: 사람 결정은 되살아난다."""
    api, ids, _, conn = seeded
    api.post(f"/api/v1/review-tasks/{ids['ref']}/dismiss", json={"reason": "내부 규정 아님", "by": "김"})
    api.post(f"/api/v1/review-tasks/{ids['parse']}/hold", json={"by": "박"})
    api.post(f"/api/v1/review-tasks/{ids['low']}/assign", json={"assignee": "이"})
    old = {r["kind"] + r["target"]: r for r in conn.execute("SELECT * FROM regulation.review_task").fetchall()}
    conn.execute("TRUNCATE regulation.review_task")
    for r in old.values():
        _task(conn, r["kind"], r["target"], r["detail"], r["work_id"])
    conn.commit()
    items = {x["kind"] + x["target"]: x for x in _items(api, status=["OPEN", "HOLD", "DISMISSED"])["items"]}
    by_old = {old[k]["id"]: items[k] for k in items}
    assert by_old[ids["ref"]]["status"] == "DISMISSED" and by_old[ids["ref"]]["decision"]["reason"] == "내부 규정 아님"
    assert by_old[ids["parse"]]["status"] == "HOLD"
    assert by_old[ids["low"]]["assignee"] == "이" and by_old[ids["low"]]["status"] == "OPEN"
    assert by_old[ids["conflict"]]["status"] == "OPEN" and by_old[ids["conflict"]]["assignee"] is None


@pytest.mark.parametrize("action,body,state,status", [
    ("resolve", {"decision": {}, "note": "기관 확인", "by": "김"}, "ABOLISHED", "RESOLVED"),
    ("dismiss", {"reason": "목록 오류", "by": "김"}, None, "DISMISSED"),
])
def test_abolished_goes_through_alio_ledger(conn, migrated, tmp_path, action, body, state, status):
    """폐지 후보는 alio_rule이 원장이다: 해결 = 폐지 확정, 문제 없음 = 현행 유지 (reconcile.decide)."""
    from datetime import timedelta

    from reg.sources.alio.reconcile import project
    from tests.sources.alio.seed import T0, add_inst, add_rule, rule

    wid = add_rule(conn, add_inst(conn), "1", T0 - timedelta(days=5))
    conn.execute("UPDATE regulation.alio_rule SET missing_since = '2026-09-28', abolish_state = 'CANDIDATE'")
    project(conn)
    conn.commit()
    with TestClient(create_app(migrated[0], LocalBlobStore(tmp_path))) as api:
        t = _items(api, kind="ABOLISHED")["items"][0]
        assert t["work_id"] == wid and "2026-09-28" in t["problem"] and t["location"]["label"] == "전체"
        r = api.post(f"/api/v1/review-tasks/{t['id']}/{action}", json=body)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == status and r.json()["decision"]["by"] == "김"
        assert rule(conn, "1")["abolish_state"] == state
        conn.commit()
        assert api.post(f"/api/v1/review-tasks/{t['id']}/{action}", json=body).status_code == 409
