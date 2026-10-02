"""Airflow·CLI 진입점 (overview §2.6). build·gate·publish 분리는 M6-4가 한다."""
from reg.platform.runs import open_conn, task_run


def build() -> dict:
    """새 release 색인을 만들고 게시한다 (현행 동작)."""
    from reg.index.indexer import build_release
    from reg.index.os import OpenSearch
    from reg.platform.llm import EmbeddingProvider
    from reg.platform.settings import get_settings

    s = get_settings()
    with open_conn() as conn, task_run("index.build", conn) as st:
        st.update(build_release(conn, OpenSearch(s.os_url), EmbeddingProvider(s.embed_url, s.embed_model),
                                s.embed_model))
        return dict(st)
