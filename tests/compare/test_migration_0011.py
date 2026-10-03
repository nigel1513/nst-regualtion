import psycopg
import pytest


def test_tables_and_indexes(conn):
    cols = {r["column_name"] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema='regulation' AND table_name='compare_cell'")}
    assert {"topic", "item", "institution_code", "work_id", "pv_id", "path", "value", "value_norm", "quote", "method",
            "confidence", "extracted_at"} <= cols
    idx = {r["indexname"] for r in conn.execute(
        "SELECT indexname FROM pg_indexes WHERE schemaname='regulation' AND tablename IN ('work_topic','compare_cell')")}
    assert {"work_topic_pkey", "work_topic_topic", "compare_cell_pkey", "compare_cell_institution"} <= idx


def test_absent_cell_needs_no_evidence_but_value_cell_does(conn):
    conn.execute("INSERT INTO regulation.compare_cell (topic, item, institution_code, method) VALUES ('travel','per_diem','KASI','absent')")
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO regulation.compare_cell (topic, item, institution_code, value, method)"
                     " VALUES ('travel','lodging_cap','KASI','7만원','llm')")
    conn.rollback()


def test_app_role_can_write(conn):
    conn.execute("INSERT INTO regulation.work_topic (work_id, topic, score, method) VALUES ('kr/reg/X/a','travel',1,'title')")
    assert conn.execute("SELECT count(*) n FROM regulation.work_topic").fetchone()["n"] == 1
    conn.rollback()
