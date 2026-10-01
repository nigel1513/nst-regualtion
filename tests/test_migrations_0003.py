def cols(conn, table):
    return {r["column_name"] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema='regulation' AND table_name=%s",
        (table,)).fetchall()}


def test_m2b_schema(conn):
    assert {"view_blob_key", "view_status"} <= cols(conn, "source_document")
    assert "validation_status" in cols(conn, "work_version")
    assert {"source_pv_id", "rel_type", "target_kind", "target_work_id", "target_path", "target_name",
            "resolution", "evidence_text"} <= cols(conn, "reference")
    assert {"kind", "target", "status", "detail"} <= cols(conn, "review_task")
    assert {"name", "origin"} <= cols(conn, "law_seed")
