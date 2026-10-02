NEW = {"work", "work_version", "amendment_history", "provision", "provision_version",
       "version_provision", "provision_change"}


def test_structure_tables_exist(conn):
    rows = conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema IN ('regulation', 'ops')").fetchall()
    assert NEW <= {r["table_name"] for r in rows}
    cols = conn.execute("SELECT column_name FROM information_schema.columns WHERE table_schema IN ('regulation', 'ops')"
                        " AND table_name='outbox'").fetchall()
    assert "last_error" in {c["column_name"] for c in cols}
