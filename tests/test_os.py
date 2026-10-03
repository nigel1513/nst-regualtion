from reg.index.os import OpenSearch
from tests.index.fakes import make_doc


def test_index_bulk_alias_and_nori(os_url):
    os = OpenSearch(os_url)
    if os.alias_target():  # 같은 세션의 다른 테스트가 남긴 색인 정리 (컨테이너는 세션 공유)
        os.delete_index(os.alias_target())
    os.put_pipeline()
    os.create_index("reg-provisions-rt1", 4)
    doc = make_doc()
    assert os.bulk("reg-provisions-rt1", [doc]) == 1
    os.refresh("reg-provisions-rt1")
    assert os.alias_target() is None and os.swap_alias("reg-provisions-rt1") is None
    assert os.alias_target() == "reg-provisions-rt1"
    hits = os.search({"query": {"match": {"text": "증빙서"}}})["hits"]["hits"]   # nori가 '증빙서를'을 '증빙서'로
    assert hits[0]["_source"]["path"] == "a27.p1"
    os.create_index("reg-provisions-rt2", 4)
    assert os.swap_alias("reg-provisions-rt2") == "reg-provisions-rt1" and os.alias_target() == "reg-provisions-rt2"
    os.delete_index("reg-provisions-rt1")
    os.delete_index("reg-provisions-rt2")


def test_release_tables(conn):
    conn.execute("INSERT INTO ops.release (state, os_index, embedding_model) VALUES ('BUILDING','x','m')")
