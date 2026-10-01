from reg.search.mapping import ALIAS
from reg.search.os import OpenSearch


def test_index_bulk_alias_and_nori(os_url):
    os = OpenSearch(os_url)
    os.put_pipeline()
    os.create_index("nais-regulations-rt1", 4)
    doc = {"chunk_id": "c1", "release_id": "t1", "work_id": "w", "version_id": "w@2024-01-17", "path": "a27",
           "path_label": "제27조(출장증빙의 제출)", "institution": "KASI", "work_kind": "INTERNAL_REG", "title": "여비규정",
           "text": "출장자는 출장 종료일 다음 날을 기점으로 7일 이내에 증빙서를 제출하여야 한다.", "context_text": "여비규정 > 보칙",
           "effective_from": "2024-01-17", "effective_to": None, "version_state": "CURRENT",
           "embedding": [0.1, 0.2, 0.3, 0.4], "embedding_model": "t"}
    assert os.bulk("nais-regulations-rt1", [doc]) == 1
    os.refresh("nais-regulations-rt1")
    assert os.alias_target() is None and os.swap_alias("nais-regulations-rt1") is None
    assert os.alias_target() == "nais-regulations-rt1"
    hits = os.search({"query": {"match": {"text": "증빙서"}}})["hits"]["hits"]   # nori가 '증빙서를'을 '증빙서'로
    assert hits[0]["_source"]["path"] == "a27"
    os.create_index("nais-regulations-rt2", 4)
    assert os.swap_alias("nais-regulations-rt2") == "nais-regulations-rt1" and os.alias_target() == "nais-regulations-rt2"
    os.delete_index("nais-regulations-rt1")
    os.delete_index("nais-regulations-rt2")


def test_release_tables(conn):
    conn.execute("INSERT INTO regulation.release (state, os_index, embedding_model) VALUES ('BUILDING','x','m')")
