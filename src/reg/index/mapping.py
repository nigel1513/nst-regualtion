ALIAS = "nais-regulations"
PIPELINE = "nais-regulations-hybrid"

PIPELINE_BODY = {
    "description": "BM25(nori) + 벡터 하이브리드 점수 결합 (spec 8.2)",
    "phase_results_processors": [{"normalization-processor": {
        "normalization": {"technique": "min_max"},
        "combination": {"technique": "arithmetic_mean", "parameters": {"weights": [0.4, 0.6]}}}}],
}


def index_body(dim: int) -> dict:
    ko = {"type": "text", "analyzer": "ko"}
    return {
        "settings": {"index": {"knn": True, "number_of_shards": 1, "number_of_replicas": 0},
                     "analysis": {"tokenizer": {"nori_mixed": {"type": "nori_tokenizer", "decompound_mode": "mixed"}},
                                  "analyzer": {"ko": {"type": "custom", "tokenizer": "nori_mixed",
                                                      "filter": ["lowercase", "nori_readingform"]}}}},
        "mappings": {"dynamic": "strict", "properties": {
            "chunk_id": {"type": "keyword"}, "release_id": {"type": "keyword"}, "work_id": {"type": "keyword"},
            "version_id": {"type": "keyword"}, "path": {"type": "keyword"}, "path_label": ko,
            "institution": {"type": "keyword"}, "work_kind": {"type": "keyword"},
            "title": {**ko, "fields": {"kw": {"type": "keyword"}}}, "text": ko, "context_text": ko,
            "effective_from": {"type": "date"}, "effective_to": {"type": "date"}, "version_state": {"type": "keyword"},
            "embedding": {"type": "knn_vector", "dimension": dim,
                          "method": {"name": "hnsw", "engine": "lucene", "space_type": "cosinesimil"}},
            "embedding_model": {"type": "keyword"}}},
    }
