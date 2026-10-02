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
