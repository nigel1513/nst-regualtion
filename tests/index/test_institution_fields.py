"""overview §2.8: 청크에 기관 코드·이름·약칭을 남기고, 검색은 코드·정식명·약칭 어느 것으로도 거른다."""
from reg.index.indexer import INDEX_FORMAT, build_release
from reg.index.service import search
from tests.index.fakes import FakeEmbedder, make_doc

LAW = "kr/law/000999"


def _set_aliases(conn):
    conn.execute("UPDATE regulation.institution SET aliases = '{천문연,천문硏}' WHERE code = 'KASI'")
    conn.commit()


def _add_law(conn):
    """KASI 현행 버전의 조항을 그대로 쓰는 법령 하나 (소관부처는 external_ids.ministry)."""
    conn.execute("INSERT INTO regulation.work (id, kind, title, external_ids) VALUES (%s, 'LAW', '국가연구개발혁신법',"
                 " '{\"ministry\": \"과학기술정보통신부\"}')", (LAW,))
    v = conn.execute("SELECT id, source_document_id FROM regulation.work_version WHERE version_state = 'CURRENT'"
                     " LIMIT 1").fetchone()
    conn.execute("INSERT INTO regulation.work_version (id, work_id, source_document_id, title, effective_from,"
                 " effective_basis, effective_status, version_state, parsed)"
                 " VALUES (%s, %s, %s, '국가연구개발혁신법', '2024-01-01', 'test', 'CONFIRMED', 'CURRENT', '{}')",
                 (LAW + "@1", LAW, v["source_document_id"]))
    conn.execute("INSERT INTO regulation.version_provision (work_version_id, provision_version_id, ord)"
                 " SELECT %s, provision_version_id, ord FROM regulation.version_provision WHERE work_version_id = %s",
                 (LAW + "@1", v["id"]))
    conn.commit()


def _docs(os, index, work_id):
    r = os.search({"size": 1, "query": {"term": {"work_id": work_id}}, "_source": {"excludes": ["embedding"]}},
                  index=index)
    return [h["_source"] for h in r["hits"]["hits"]]


def test_index_format_bumped_for_institution_fields():
    assert "institution" in INDEX_FORMAT


def test_chunks_carry_institution_name_and_aliases(loaded, osx):
    _set_aliases(loaded)
    st = build_release(loaded, osx, FakeEmbedder(), "fake")
    d = _docs(osx, st["index"], "kr/reg/KASI/여비규정")[0]
    assert d["institution"] == "KASI" and d["institution_name"] == "한국천문연구원"
    assert d["institution_aliases"] == ["천문연", "천문硏"]


def test_law_chunks_use_ministry_as_institution_name(loaded, osx):
    _add_law(loaded)
    st = build_release(loaded, osx, FakeEmbedder(), "fake")
    d = _docs(osx, st["index"], LAW)[0]
    assert d["institution"] == "LAW" and d["institution_name"] == "과학기술정보통신부"
    assert d["institution_aliases"] == []


def _ids(r):
    return [(h["work_id"], h["path"]) for h in r["hits"]]


def test_search_accepts_code_name_or_alias(loaded, osx):
    _set_aliases(loaded)
    build_release(loaded, osx, FakeEmbedder(), "fake")
    by_code = search(osx, FakeEmbedder(), None, "증빙서", institution="KASI", rerank=False)
    assert by_code["hits"]
    assert _ids(search(osx, FakeEmbedder(), None, "증빙서", institution="천문연", rerank=False)) == _ids(by_code)
    assert _ids(search(osx, FakeEmbedder(), None, "증빙서", institution="한국천문연구원", rerank=False)) == _ids(by_code)
    assert search(osx, FakeEmbedder(), None, "증빙서", institution="없는기관", rerank=False)["hits"] == []


def test_hits_carry_institution_name(loaded, osx):
    build_release(loaded, osx, FakeEmbedder(), "fake")
    h = search(osx, FakeEmbedder(), None, "증빙서", institution="KASI", rerank=False)["hits"][0]
    assert h["institution_name"] == "한국천문연구원"


def test_institution_name_in_question_boosts_bm25(osx):
    from reg.platform.llm import ProviderError

    class Down:
        def embed(self, texts):
            raise ProviderError("down")

    base = make_doc(text="출장 여비는 규정에 따라 정산한다.")
    docs = [{**base, "doc_id": "e", "article_key": "e|a1", "work_id": "kr/reg/ETRI/여비규정", "institution": "ETRI",
             "institution_name": "한국전자통신연구원", "institution_aliases": ["에트리"], "breadcrumb": "한국전자통신연구원 > 여비규정"},
            {**base, "doc_id": "k", "article_key": "k|a1", "work_id": "kr/reg/KASI/여비규정", "institution": "KASI",
             "institution_name": "한국천문연구원", "institution_aliases": ["천문연"], "breadcrumb": "한국천문연구원 > 여비규정"}]
    osx.create_index("reg-provisions-r903", 4)
    osx.bulk("reg-provisions-r903", docs)
    osx.refresh("reg-provisions-r903")
    r = search(osx, Down(), None, "한국천문연구원 출장 여비 정산", rerank=False, index="reg-provisions-r903")
    assert r["mode"] == "bm25" and [h["institution"] for h in r["hits"]] == ["KASI", "ETRI"]
