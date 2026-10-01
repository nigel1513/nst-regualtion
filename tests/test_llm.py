import json

import httpx
import pytest
import respx

from reg.llm import EmbeddingProvider, LLMProvider, ProviderError, RerankProvider


@respx.mock
def test_embed_batches_and_keeps_order():
    def reply(req):
        inp = json.loads(req.content)["input"]
        return httpx.Response(200, json={"data": [{"index": i, "embedding": [float(len(t)), 0.0]} for i, t in enumerate(inp)]})
    route = respx.post("http://e/v1/embeddings").mock(side_effect=reply)
    vecs = EmbeddingProvider("http://e", "bge-m3", batch=2).embed(["a", "bb", "ccc"])
    assert [v[0] for v in vecs] == [1.0, 2.0, 3.0] and route.call_count == 2


@respx.mock
def test_embed_retries_then_raises():
    respx.post("http://e/v1/embeddings").respond(503)
    with pytest.raises(ProviderError):
        EmbeddingProvider("http://e", "bge-m3", retry_wait=0).embed(["a"])


@respx.mock
def test_rerank_sorted():
    respx.post("http://r/rerank").respond(200, json={"results": [{"index": 0, "relevance_score": 0.1},
                                                                  {"index": 1, "relevance_score": 0.9}]})
    assert RerankProvider("http://r", "m").rerank("q", ["x", "y"]) == [(1, 0.9), (0, 0.1)]


@respx.mock
def test_llm_json_retries_bad_json_once():
    route = respx.post("http://l/v1/chat/completions")
    route.side_effect = [httpx.Response(200, json={"choices": [{"message": {"content": "{bad"}}]}),
                         httpx.Response(200, json={"choices": [{"message": {"content": '{"a": 1}'}}]})]
    assert LLMProvider("http://l", "llm").json([{"role": "user", "content": "x"}], {"type": "object"}) == {"a": 1}
