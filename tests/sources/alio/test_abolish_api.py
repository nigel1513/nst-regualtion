from datetime import date, timedelta

from reg.api import queries as Q
from reg.sources.alio.reconcile import project
from tests.sources.alio.seed import T0, add_inst, add_rule


def test_works_and_work_carry_status(conn):
    inst = add_inst(conn)
    wid = add_rule(conn, inst, "1", T0 - timedelta(days=5))
    live = add_rule(conn, inst, "2", T0)
    conn.execute("UPDATE regulation.alio_rule SET missing_since = '2026-09-28', abolish_state = 'ABOLISHED',"
                 " abolished_on = '2026-09-28' WHERE seq = '1'")
    project(conn)
    conn.commit()
    rows = {r["id"]: r for r in Q.works(conn, "KASI", None, None)}
    assert rows[wid]["status"] == "ABOLISHED" and rows[wid]["abolished_on"] == date(2026, 9, 28)
    assert rows[live]["status"] == "ACTIVE" and rows[live]["abolished_on"] is None
    assert Q.work(conn, wid)["status"] == "ABOLISHED"


def test_review_queue_lists_abolished_candidates(conn):
    inst = add_inst(conn)
    wid = add_rule(conn, inst, "1", T0 - timedelta(days=5))
    conn.execute("UPDATE regulation.alio_rule SET missing_since = '2026-09-28', abolish_state = 'CANDIDATE' WHERE seq = '1'")
    project(conn)
    conn.commit()
    t = Q.review_tasks(conn, "OPEN", "ABOLISHED")
    assert [(x["kind"], x["work_id"], x["work_title"]) for x in t] == [("ABOLISHED", wid, "규정1")]
    assert t[0]["detail"]["missing_since"] == "2026-09-28"
