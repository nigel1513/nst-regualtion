def _indexes(conn, table):
    return {r["indexdef"].split(" USING btree ")[-1] for r in conn.execute(
        "SELECT indexdef FROM pg_indexes WHERE schemaname = 'regulation' AND tablename = %s", (table,))}


def test_work_id_indexes_for_rebuild_deletes(conn):
    """재적재 때 work_id로 지우는 두 테이블과 대상만으로 찾는 검수 작업 (docs/tech/03-rdb.md §8)."""
    assert "(work_id)" in _indexes(conn, "provision_change")
    assert "(work_id)" in _indexes(conn, "reference")
    assert "(target)" in _indexes(conn, "review_task")


def test_alio_seq_lookup_uses_the_partial_index(conn):
    from reg.core.ingest.loader import WORK_BY_ALIO_SEQ

    conn.execute("SET enable_seqscan = off")
    plan = "\n".join(r["QUERY PLAN"] for r in conn.execute("EXPLAIN " + WORK_BY_ALIO_SEQ, ("123",)))
    assert "work_alio_seq" in plan
