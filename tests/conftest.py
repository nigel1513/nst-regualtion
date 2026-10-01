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
            "TRUNCATE regulation.qa_log, regulation.release_item, regulation.release, regulation.reference, regulation.review_task, regulation.law_seed, regulation.provision_change, regulation.version_provision, regulation.provision_version,"
            " regulation.provision, regulation.amendment_history, regulation.work_version, regulation.work,"
            " regulation.outbox, regulation.alio_rule_file, regulation.alio_rule,"
            " regulation.law_watch, regulation.request_log, regulation.fetch_run,"
            " regulation.source_document, regulation.institution CASCADE"
        )
    c.commit()
    c.close()


@pytest.fixture(scope="session")
def os_url():
    import time

    import httpx
    from testcontainers.core.container import DockerContainer

    c = (DockerContainer("nais-opensearch:2.19.1-nori").with_exposed_ports(9200)
         .with_env("discovery.type", "single-node").with_env("DISABLE_SECURITY_PLUGIN", "true")
         .with_env("DISABLE_INSTALL_DEMO_CONFIG", "true").with_env("OPENSEARCH_JAVA_OPTS", "-Xms512m -Xmx512m"))
    with c:
        url = f"http://{c.get_container_host_ip()}:{c.get_exposed_port(9200)}"
        for _ in range(90):
            try:
                if httpx.get(f"{url}/_cluster/health", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(1)
        yield url


@pytest.fixture
def loaded(conn, tmp_path):
    """천문연 여비규정(실파일)을 처리까지 마친 DB 연결."""
    from datetime import date

    from reg.process import process_once
    from reg.storage.blob import LocalBlobStore
    from tests.test_process import FX, seed_alio

    blob = LocalBlobStore(tmp_path)
    seed_alio(conn, blob, (FX / "samples" / "kasi-yeobi-339.pdf").read_bytes())
    process_once(conn, blob, today=date(2026, 10, 2))
    return conn
