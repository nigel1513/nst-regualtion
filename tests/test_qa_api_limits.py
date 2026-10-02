import respx
from fastapi.testclient import TestClient
from httpx import Response

from reg.api.app import create_app
from reg.platform.llm import EmbeddingProvider, ProviderError
from reg.platform.storage.blob import LocalBlobStore


class FakeOS:
    def alias_target(self):
        return "idx"


def test_qa_rejects_when_all_slots_busy(migrated, tmp_path):
    app = create_app(migrated[0], LocalBlobStore(tmp_path), search_deps={"os": FakeOS()})
    with TestClient(app) as c:
        for _ in range(app.state.qa_slots._value):
            app.state.qa_slots.acquire()
        r = c.post("/api/v1/qa", json={"question": "천문연 출장 증빙 기한"})
        assert r.status_code == 429


def test_feedback_reason_is_bounded(migrated, tmp_path):
    with TestClient(create_app(migrated[0], LocalBlobStore(tmp_path))) as c:
        assert c.post("/api/v1/qa/1/feedback", json={"feedback": "not_helpful", "reason": "x" * 2000}).status_code == 422


@respx.mock
def test_query_time_embedder_fails_fast():
    route = respx.post("http://e/v1/embeddings").mock(return_value=Response(503))
    p = EmbeddingProvider("http://e", "m", timeout=3, tries=1)
    try:
        p.embed(["q"])
    except ProviderError:
        pass
    assert route.call_count == 1
