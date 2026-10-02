def test_ops_schema_and_m6_columns(conn):
    tables = {(r["table_schema"], r["table_name"]) for r in conn.execute(
        "SELECT table_schema, table_name FROM information_schema.tables"
        " WHERE table_schema IN ('regulation', 'ops')").fetchall()}
    for t in ("outbox", "fetch_run", "request_log", "release", "release_item", "qa_log", "change_impact",
              "owner_assignment", "notification", "email_delivery", "pipeline_run", "embedding_cache"):
        assert ("ops", t) in tables and ("regulation", t) not in tables
    cols = {(r["table_name"], r["column_name"]) for r in conn.execute(
        "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'regulation'").fetchall()}
    assert {("work", "status"), ("work", "abolished_on"), ("work_version", "parser_version"),
            ("source_document", "ocr_status"), ("source_document", "ocr_blob_key"), ("source_document", "ocr_engine"),
            ("alio_rule", "missing_since")} <= cols
    assert conn.execute("SELECT count(*) AS n FROM regulation.alembic_version_alio").fetchone()["n"] == 1
    conn.execute("INSERT INTO ops.pipeline_run (dag_id, task_id) VALUES ('d', 't')")  # reg_app이 쓴다


def test_institution_aliases_and_master_view(conn):
    conn.execute("INSERT INTO regulation.institution (code, name, kind, aliases) VALUES ('KASI', '한국천문연구원', 'GRI',"
                 " ARRAY['천문연'])")
    conn.execute("INSERT INTO regulation.work (id, kind, title, institution_id) SELECT 'kr/reg/KASI/여비', 'INTERNAL_REG',"
                 " '여비규정', id FROM regulation.institution WHERE code = 'KASI'")
    r = conn.execute("SELECT * FROM regulation.v_regulation_master WHERE work_id = 'kr/reg/KASI/여비'").fetchone()
    assert (r["institution_code"], r["institution_name"], r["title"], r["status"]) == ("KASI", "한국천문연구원", "여비규정", "ACTIVE")
    assert r["institution_aliases"] == ["천문연"] and r["current_version_id"] is None and r["provisions"] == 0
