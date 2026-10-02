import psycopg

from reg.platform.db.bootstrap import bootstrap
from tests.conftest import _dsn


def test_bootstrap_creates_dedicated_db_and_schemas_idempotently(pg):
    su = _dsn(pg, "su", "su", pg.dbname)
    bootstrap(su, "nst_regulation", "mig", "app")
    bootstrap(su, "nst_regulation", "mig", "app")  # 두 번째도 오류 없이
    with psycopg.connect(_dsn(pg, "reg_migrator", "mig", "nst_regulation")) as c:
        got = {r[0] for r in c.execute("SELECT nspname FROM pg_namespace").fetchall()}
        assert {"regulation", "law", "ops"} <= got
        c.execute("CREATE TABLE ops.t_probe (x int)")
        c.commit()
    with psycopg.connect(_dsn(pg, "reg_app", "app", "nst_regulation")) as c:
        c.execute("INSERT INTO ops.t_probe VALUES (1)")  # 기본 권한으로 reg_app이 쓴다
        c.commit()
