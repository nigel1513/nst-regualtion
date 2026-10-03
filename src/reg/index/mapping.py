"""조·항·호·목 단위 색인 매핑 (M7 spec §2.1). 문서 필드는 reg.index.units.unit_docs가 만든다."""
ALIAS = "reg-provisions"
PIPELINE = "reg-provisions-hybrid"

PIPELINE_BODY = {
    "description": "BM25(nori) + 벡터 하이브리드 점수 결합 (M7 spec §2.2: min_max, 0.4/0.6)",
    "phase_results_processors": [{"normalization-processor": {
        "normalization": {"technique": "min_max"},
        "combination": {"technique": "arithmetic_mean", "parameters": {"weights": [0.4, 0.6]}}}}],
}


def index_body(dim: int, synonyms: list[str] | None = None, userdict: list[str] | None = None) -> dict:
    tokenizer = {"type": "nori_tokenizer", "decompound_mode": "mixed"}
    if userdict:
        tokenizer["user_dictionary_rules"] = userdict
    base_filters = ["lowercase", "nori_readingform"]
    # 검색 분석기는 복합어를 부분으로만 낸다(discard): mixed는 같은 자리에 복합어·부분을 함께 내서
    # synonym_graph가 "출장비" 같은 규칙을 읽지 못한다(lenient로 조용히 버려짐). 색인(mixed)에는 부분이 다 있다.
    search_tokenizer = {**tokenizer, "decompound_mode": "discard"}
    analysis = {"tokenizer": {"nori_mixed": tokenizer, "nori_discard": search_tokenizer},
                "filter": {"ko_synonyms": {"type": "synonym_graph", "lenient": True,
                                           "synonyms": synonyms or ["출장비, 여비"]}},
                "analyzer": {"ko": {"type": "custom", "tokenizer": "nori_mixed", "filter": base_filters},
                             "ko_syn": {"type": "custom", "tokenizer": "nori_discard",
                                        "filter": [*base_filters, "ko_synonyms"]}}}
    ko = {"type": "text", "analyzer": "ko"}
    ko_syn = {"type": "text", "analyzer": "ko", "search_analyzer": "ko_syn"}   # 동의어는 검색할 때만
    kw = {"type": "keyword"}
    num = {"type": "integer"}
    return {
        "settings": {"index": {"knn": True, "number_of_shards": 1, "number_of_replicas": 0}, "analysis": analysis},
        "mappings": {"dynamic": "strict", "properties": {
            "doc_id": kw, "release_id": kw, "pv_id": {"type": "long"}, "work_id": kw, "version_id": kw,
            "path": kw, "base_path": kw, "parent_path": kw, "article_path": kw, "article_key": kw,
            "unit": kw, "window": num, "ord": num,
            "article_no": num, "article_branch": num, "paragraph_no": num, "item_no": num, "item_branch": num,
            "subitem": kw, "annex_no": num, "annex_branch": num,
            "label": kw, "marker": {"type": "keyword", "index": False},
            "full_label": {**ko, "fields": {"kw": kw}},
            "heading": ko_syn,
            "title": {**ko, "fields": {"kw": kw}},
            # 자동완성은 공백 단위(standard): nori mixed는 같은 자리에 토큰을 겹쳐 내서 shingle(_2gram·_3gram)이 깨진다
            # (실데이터 "희망퇴직요령" 등 26건, 2026-10-03). 낱말 앞부분으로 찾으므로 형태소 분석도 필요 없다.
            "title_suggest": {"type": "search_as_you_type", "analyzer": "standard"},
            "institution": kw, "institution_name": {**ko, "fields": {"kw": kw}}, "institution_aliases": kw,
            "family": kw, "work_kind": kw,
            "effective_from": {"type": "date"}, "effective_to": {"type": "date"}, "version_state": kw,
            "text": ko_syn, "article_text": ko_syn, "breadcrumb": ko_syn,
            "context": {"type": "text", "index": False},
            "annex_image": {"type": "keyword", "index": False},
            "embedding": {"type": "knn_vector", "dimension": dim,
                          "method": {"name": "hnsw", "engine": "lucene", "space_type": "cosinesimil"}},
            "embedding_model": kw}},
    }
