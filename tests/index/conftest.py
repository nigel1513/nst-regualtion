import pytest

from reg.index.os import OpenSearch


@pytest.fixture(autouse=True)
def _empty_embedding_cache(migrated):
    """캐시는 루트 conftest의 TRUNCATE 대상이 아닐 수 있으므로 색인 테스트마다 비운다."""
    from reg.platform.db.conn import connect

    c = connect(migrated[0])
    c.execute("DELETE FROM ops.embedding_cache")
    c.commit()
    c.close()


@pytest.fixture
def osx(os_url) -> OpenSearch:
    """다른 테스트가 남긴 nais-regulations-* 색인을 모두 지운 OpenSearch (컨테이너는 세션 공유)."""
    os = OpenSearch(os_url)
    for name in os.indexes():
        os.delete_index(name)
    return os
