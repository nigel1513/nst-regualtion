"""색인 모듈 테스트 대역. 벡터는 텍스트 길이로만 정해져 같은 텍스트면 늘 같다."""
from reg.platform.llm import ProviderError


class FakeEmbedder:
    dim = 4

    def __init__(self, fail_after: int | None = None, delay: float = 0.0):
        self.fail_after, self.delay = fail_after, delay
        self.calls, self.texts, self.max_batch = 0, 0, 0

    def embed(self, texts):
        if self.delay:
            import time
            time.sleep(self.delay)
        if self.fail_after is not None and self.texts + len(texts) > self.fail_after:
            raise ProviderError("down")
        self.calls += 1
        self.texts += len(texts)
        self.max_batch = max(self.max_batch, len(texts))
        return [[float(len(t) % 7), 1.0, 0.5, 0.25] for t in texts]


class FakeReranker:
    def rerank(self, q, docs):
        return sorted(((i, 1.0 if "7일 이내에 출장을 확인" in d else 0.0) for i, d in enumerate(docs)),
                      key=lambda x: -x[1])


SMOKE_OK = [{"id": "kasi-a27", "query": "출장 증빙 제출 기한", "institution": "KASI",
             "work_contains": "KASI/여비규정", "article": "a27"}]
SMOKE_BAD = [{"id": "kasi-a999", "query": "출장 증빙 제출 기한", "institution": "KASI",
              "work_contains": "KASI/여비규정", "article": "a999"}]


def make_doc(**over) -> dict:
    """조항 단위 문서 한 건 (reg.index.units.unit_docs가 만드는 모양). over로 필드를 바꾼다."""
    d = {"doc_id": "v1|a27.p1", "release_id": "t1", "pv_id": 1, "work_id": "kr/reg/KASI/여비규정", "version_id": "v1",
         "path": "a27.p1", "base_path": "a27.p1", "parent_path": "a27", "article_path": "a27", "article_key": "v1|a27",
         "unit": "paragraph", "window": 0, "ord": 1, "article_no": 27, "article_branch": 0, "paragraph_no": 1,
         "label": "제1항", "marker": "①", "full_label": "여비규정 제27조 제1항", "heading": "출장증빙의 제출",
         "title": "여비규정", "title_suggest": "여비규정", "institution": "KASI", "institution_name": "한국천문연구원",
         "institution_aliases": ["천문연"], "family": "reg", "work_kind": "INTERNAL_REG",
         "effective_from": "2024-01-17", "effective_to": None, "version_state": "CURRENT",
         "text": "출장자는 출장 종료일 다음 날을 기점으로 7일 이내에 증빙서를 제출하여야 한다.",
         "breadcrumb": "한국천문연구원 > 여비규정 > 제27조(출장증빙의 제출) > 제1항", "context": "제27조(출장증빙의 제출)",
         "embedding": [0.1, 0.2, 0.3, 0.4], "embedding_model": "t"}
    d.update(over)
    return d
