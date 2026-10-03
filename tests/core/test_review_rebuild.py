"""사람의 검수 결정은 재적재(reg process --rebuild)·재처리 뒤에도 남는다 (마이그레이션 0013 + core.review)."""
import json
from datetime import date

from reg.core import review as R
from reg.core.ingest.process import process_once, rebuild_all
from reg.core.quality import Issue, record, record_reference_tasks
from reg.platform.storage.blob import LocalBlobStore


def _tasks(conn):
    return {(r["kind"], r["target"]): r for r in conn.execute("SELECT * FROM regulation.review_task").fetchall()}


def test_full_rebuild_keeps_human_decisions(loaded, tmp_path):
    conn = loaded
    before = _tasks(conn)
    refs = [t for (k, _), t in before.items() if k == "REFERENCE"]
    assert len(refs) >= 2, "fixture에 미해석 참조 작업이 있어야 한다"
    R.dismiss(conn, refs[0]["id"], "외부 지침이라 연결 대상 없음", "김검수")
    R.hold(conn, refs[1]["id"], "법무 확인 중", "박")
    conn.commit()

    rebuild_all(conn)
    assert _tasks(conn) == {}
    process_once(conn, LocalBlobStore(tmp_path), today=date(2026, 10, 2))
    after = _tasks(conn)
    assert after.keys() == before.keys()
    a, b = after[("REFERENCE", refs[0]["target"])], after[("REFERENCE", refs[1]["target"])]
    assert (a["status"], a["decision"]["by"], a["decision"]["reason"]) == ("DISMISSED", "김검수", "외부 지침이라 연결 대상 없음")
    assert a["resolved_at"] is not None
    assert (b["status"], b["decision"]["note"]) == ("HOLD", "법무 확인 중")
    untouched = [t for key, t in after.items() if key not in {("REFERENCE", refs[0]["target"]),
                                                               ("REFERENCE", refs[1]["target"])}]
    assert all(t["status"] == before[(t["kind"], t["target"])]["status"] for t in untouched)


def _work(conn):
    conn.execute("INSERT INTO regulation.work (id, kind, title) VALUES ('kr/reg/T/a', 'INTERNAL_REG', 'a')")


def test_held_task_is_auto_closed_when_problem_disappears(conn):
    _work(conn)
    conn.execute("INSERT INTO regulation.review_task (kind, target, work_id, detail, status)"
                 " VALUES ('REFERENCE', 'ref:kr/reg/T/a:a1:0:X', 'kr/reg/T/a', '{}', 'HOLD')")
    record_reference_tasks(conn, "kr/reg/T/a")   # 미해석 참조가 이제 없다
    assert _tasks(conn)[("REFERENCE", "ref:kr/reg/T/a:a1:0:X")]["status"] == "RESOLVED"


def test_record_closes_held_version_task(conn):
    _work(conn)
    conn.execute("INSERT INTO regulation.review_task (kind, target, work_id, detail, status)"
                 " VALUES ('PARSE', 'v1', 'kr/reg/T/a', '{}', 'HOLD')")
    record(conn, "kr/reg/T/a", "v1", [Issue("EFFECTIVE_DATE", {"basis": "none"})])
    t = _tasks(conn)
    assert t[("PARSE", "v1")]["status"] == "RESOLVED" and t[("EFFECTIVE_DATE", "v1")]["status"] == "OPEN"


def test_law_link_does_not_reopen_human_resolution(conn):
    from reg.sources.lawgo.link import _sync_tasks

    _work(conn)
    conn.execute("INSERT INTO regulation.review_task (kind, target, work_id, detail, status, decision) VALUES"
                 " ('REF_LAW_AMBIGUOUS', 'ref:kr/reg/T/a:a1:0:법', 'kr/reg/T/a', '{}', 'RESOLVED', %s),"
                 " ('REF_LAW_AMBIGUOUS', 'ref:kr/reg/T/a:a2:0:법', 'kr/reg/T/a', '{}', 'RESOLVED', NULL),"
                 " ('REF_LAW_GONE', 'ref:kr/reg/T/a:a3:0:법', 'kr/reg/T/a', '{}', 'HOLD', NULL)",
                 (json.dumps({"action": "resolve", "by": "김"}),))
    _sync_tasks(conn, {("REF_LAW_AMBIGUOUS", "ref:kr/reg/T/a:a1:0:법"): ("kr/reg/T/a", {"name": "법"}),
                       ("REF_LAW_AMBIGUOUS", "ref:kr/reg/T/a:a2:0:법"): ("kr/reg/T/a", {"name": "법"})})
    t = _tasks(conn)
    assert t[("REF_LAW_AMBIGUOUS", "ref:kr/reg/T/a:a1:0:법")]["status"] == "RESOLVED"   # 사람 결정 유지
    assert t[("REF_LAW_AMBIGUOUS", "ref:kr/reg/T/a:a2:0:법")]["status"] == "OPEN"       # 자동 해결은 다시 연다
    assert t[("REF_LAW_GONE", "ref:kr/reg/T/a:a3:0:법")]["status"] == "RESOLVED"        # 사라진 문제는 보류도 닫는다


def test_abolish_projection_keeps_hold(conn):
    from datetime import timedelta

    from reg.sources.alio.reconcile import project
    from tests.sources.alio.seed import T0, add_inst, add_rule

    add_rule(conn, add_inst(conn), "1", T0 - timedelta(days=5))
    conn.execute("UPDATE regulation.alio_rule SET missing_since = '2026-09-28', abolish_state = 'CANDIDATE'")
    project(conn)
    tid = conn.execute("SELECT id FROM regulation.review_task WHERE kind = 'ABOLISHED'").fetchone()["id"]
    R.hold(conn, tid, "기관 회신 대기", "김")
    assert project(conn)["tasks_opened"] == 0
    assert conn.execute("SELECT status FROM regulation.review_task WHERE id = %s", (tid,)).fetchone()["status"] == "HOLD"
