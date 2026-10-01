import pytest
from testcontainers.community.postgres import PostgresContainer

from reg.db.bootstrap import bootstrap
from reg.db.migrate import upgrade


def _dsn(c: PostgresContainer, user: str, pw: str) -> str:
    host, port = c.get_container_host_ip(), c.get_exposed_port(5432)
    return f"postgresql://{user}:{pw}@{host}:{port}/{c.dbname}"


@pytest.fixture(scope="session")
def pg():
    with PostgresContainer("postgres:16", username="su", password="su", dbname="nais") as c:
        yield c


@pytest.fixture(scope="session")
def migrated(pg):
    su = _dsn(pg, "su", "su")
    bootstrap(su, "nais", "mig", "app")
    mig, app = _dsn(pg, "reg_migrator", "mig"), _dsn(pg, "reg_app", "app")
    upgrade(mig)
    return app, mig


@pytest.fixture
def conn(migrated):
    from reg.db.conn import connect

    c = connect(migrated[0])
    yield c
    c.rollback()
    with c.cursor() as cur:  # 테스트 간 격리: 데이터만 비운다
        cur.execute(
            "TRUNCATE regulation.reference, regulation.review_task, regulation.law_seed, regulation.provision_change, regulation.version_provision, regulation.provision_version,"
            " regulation.provision, regulation.amendment_history, regulation.work_version, regulation.work,"
            " regulation.outbox, regulation.alio_rule_file, regulation.alio_rule,"
            " regulation.law_watch, regulation.request_log, regulation.fetch_run,"
            " regulation.source_document, regulation.institution CASCADE"
        )
    c.commit()
    c.close()
