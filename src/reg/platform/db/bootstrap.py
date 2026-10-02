"""공유 Postgres 서버에 이 프로젝트 전용 DB(nst_regulation)·역할·스키마를 만든다. 슈퍼유저 DSN으로 실행 (멱등)."""
from urllib.parse import urlparse, urlunparse

import psycopg
from psycopg import sql

SCHEMAS = ("regulation", "law", "ops")


def _ensure_role(cur, name: str, password: str) -> None:
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (name,))
    verb = "ALTER" if cur.fetchone() else "CREATE"
    cur.execute(sql.SQL(verb + " ROLE {} LOGIN PASSWORD {}").format(sql.Identifier(name), sql.Literal(password)))


def _with_db(dsn: str, db: str) -> str:
    u = urlparse(dsn)
    return urlunparse(u._replace(path="/" + db))


def bootstrap(superuser_dsn: str, db_name: str, migrator_password: str, app_password: str) -> None:
    db = sql.Identifier(db_name)
    with psycopg.connect(superuser_dsn, autocommit=True) as c, c.cursor() as cur:
        _ensure_role(cur, "reg_migrator", migrator_password)
        _ensure_role(cur, "reg_app", app_password)
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
        if not cur.fetchone():
            cur.execute(sql.SQL("CREATE DATABASE {} OWNER reg_migrator").format(db))
        cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO reg_migrator, reg_app").format(db))
    with psycopg.connect(_with_db(superuser_dsn, db_name), autocommit=True) as c, c.cursor() as cur:
        for s in SCHEMAS:
            name = sql.Identifier(s)
            cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {} AUTHORIZATION reg_migrator").format(name))
            cur.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO reg_app").format(name))
            cur.execute(sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE reg_migrator IN SCHEMA {}"
                                " GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON TABLES TO reg_app").format(name))
            cur.execute(sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE reg_migrator IN SCHEMA {}"
                                " GRANT USAGE, SELECT ON SEQUENCES TO reg_app").format(name))
