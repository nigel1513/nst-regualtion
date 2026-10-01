def test_alert_tables(conn):
    names = {r["table_name"] for r in conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='regulation'").fetchall()}
    assert {"change_impact", "owner_assignment", "notification", "email_delivery"} <= names
