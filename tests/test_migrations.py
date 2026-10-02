import psycopg
import pytest

from reg.platform.db.bootstrap import bootstrap
from tests.conftest import _dsn

TABLES = {"institution", "fetch_run", "request_log", "source_document",
          "alio_rule", "alio_rule_file", "law_watch", "outbox"}


def test_tables_exist_and_app_can_write(conn):
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='regulation'"
    ).fetchall()
    assert TABLES <= {r["table_name"] for r in rows}
    conn.execute("INSERT INTO regulation.outbox (topic, payload) VALUES ('t', '{}')")


def test_app_cannot_create_tables(conn):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("CREATE TABLE regulation.nope (x int)")


def test_bootstrap_is_idempotent(pg, migrated):
    bootstrap(_dsn(pg, "su", "su"), "nais", "mig", "app")  # 두 번째 실행도 오류 없음
