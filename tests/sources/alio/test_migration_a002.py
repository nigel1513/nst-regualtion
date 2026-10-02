import psycopg
import pytest

from reg.sources.alio.migrations.versions.a002_abolish import ADD_KIND, DROP_KIND

OLD_KINDS = ["PARSE", "EFFECTIVE_DATE", "REFERENCE", "CONFLICT", "LOW_TEXT"]


def _kind_check(conn) -> str:
    return conn.execute(
        "SELECT pg_get_constraintdef(oid) AS d FROM pg_constraint"
        " WHERE conrelid = 'regulation.review_task'::regclass AND conname = 'review_task_kind_check'").fetchone()["d"]


def test_review_task_accepts_abolished_and_keeps_old_kinds(conn):
    d = _kind_check(conn)
    assert all(f"'{k}'" in d for k in OLD_KINDS + ["ABOLISHED"])
    conn.execute("INSERT INTO regulation.review_task (kind, target) VALUES ('ABOLISHED', 'work:x'), ('PARSE', 'v1')")
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO regulation.review_task (kind, target) VALUES ('BOGUS', 'y')")
    conn.rollback()


def _kinds(check: str) -> set[str]:
    """CHECK 정의 속 허용 종류 집합 (다른 모듈 이력이 종류를 더하면 순서는 바뀔 수 있다)."""
    import re

    return set(re.findall(r"'([A-Za-z_]+)'", check))


def test_add_kind_block_is_idempotent(migrated, conn):
    before = _kinds(_kind_check(conn))
    conn.rollback()
    with psycopg.connect(migrated[1], autocommit=True) as mig:   # 다른 트랙이 먼저 추가했거나 두 번 돌아도 그대로
        mig.execute(ADD_KIND)
        mig.execute(ADD_KIND)
    assert _kinds(_kind_check(conn)) == before
    conn.rollback()
    with psycopg.connect(migrated[1], autocommit=True) as mig:   # 내림 → 다시 올림이 원래 제약으로 돌아온다
        mig.execute(DROP_KIND)
        assert "ABOLISHED" not in _kind_check(mig.cursor(row_factory=psycopg.rows.dict_row))
        mig.execute(ADD_KIND)
    assert _kinds(_kind_check(conn)) == before


def test_alio_rule_has_abolish_ledger_columns(conn):
    cols = {r["column_name"]: r["data_type"] for r in conn.execute(
        "SELECT column_name, data_type FROM information_schema.columns"
        " WHERE table_schema = 'regulation' AND table_name = 'alio_rule'").fetchall()}
    assert cols["missing_since"] == "date" and cols["abolished_on"] == "date" and cols["abolish_state"] == "text"
    inst = conn.execute("INSERT INTO regulation.institution (code, name, kind) VALUES ('T','T','GRI') RETURNING id").fetchone()["id"]
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO regulation.alio_rule (seq, institution_id, title, abolish_state)"
                     " VALUES ('1', %s, 't', 'GONE')", (inst,))
    conn.rollback()
