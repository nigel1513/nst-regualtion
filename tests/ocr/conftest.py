import pytest

from reg.platform.storage.blob import LocalBlobStore


def pytest_configure(config):
    config.addinivalue_line("markers", "mineru_live: 실서버 MinerU(REG_MINERU_URL)가 필요")


@pytest.fixture
def blob(tmp_path):
    return LocalBlobStore(tmp_path)


@pytest.fixture
def seeded(conn, blob):
    """조문 번호 숫자가 깨진 실제 PDF 하나를 수집 이벤트까지 넣는다. source_document id를 돌려준다."""
    from tests.ocr.fx import BROKEN
    from tests.test_process import seed_alio

    seed_alio(conn, blob, BROKEN.read_bytes(), file_name="방사선재해보상기준.pdf")
    return conn.execute("SELECT id FROM regulation.source_document").fetchone()["id"]
