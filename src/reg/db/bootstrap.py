"""공유 Postgres에 이 프로젝트 전용 역할·스키마를 만든다. 슈퍼유저 DSN으로 한 번 실행한다 (멱등)."""
import psycopg
from psycopg import sql


def _ensure_role(cur, name: str, password: str) -> None:
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (name,))
    verb = "ALTER" if cur.fetchone() else "CREATE"
    cur.execute(sql.SQL(verb + " ROLE {} LOGIN PASSWORD {}").format(
        sql.Identifier(name), sql.Literal(password)))


def bootstrap(superuser_dsn: str, db_name: str, migrator_password: str, app_password: str) -> None:
    with psycopg.connect(superuser_dsn, autocommit=True) as c, c.cursor() as cur:
        _ensure_role(cur, "reg_migrator", migrator_password)
        _ensure_role(cur, "reg_app", app_password)
        db = sql.Identifier(db_name)
        cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO reg_migrator, reg_app").format(db))
        cur.execute("CREATE SCHEMA IF NOT EXISTS regulation AUTHORIZATION reg_migrator")
        cur.execute("GRANT USAGE ON SCHEMA regulation TO reg_app")
        cur.execute("ALTER DEFAULT PRIVILEGES FOR ROLE reg_migrator IN SCHEMA regulation"
                    " GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON TABLES TO reg_app")
        cur.execute("ALTER DEFAULT PRIVILEGES FOR ROLE reg_migrator IN SCHEMA regulation"
                    " GRANT USAGE, SELECT ON SEQUENCES TO reg_app")
