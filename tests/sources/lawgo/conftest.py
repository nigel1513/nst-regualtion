import pytest

from reg.platform.storage.blob import LocalBlobStore

LAW_TABLES = ("law.change_log, law.sync_run, law.annex, law.article, law.law_version, law.law_master,"
              " law.admrul_catalog")


@pytest.fixture
def lconn(conn):
    """core conn + 끝에 law 스키마도 비운다 (law_master TRUNCATE는 regulation.work까지 CASCADE)."""
    yield conn
    conn.rollback()
    conn.execute(f"TRUNCATE {LAW_TABLES} CASCADE")
    conn.commit()


@pytest.fixture
def blob(tmp_path):
    return LocalBlobStore(tmp_path)
