"""vLLM(OpenAI 호환) Provider. 모델과 서버 위치는 설정으로만 바뀐다 (spec D-10)."""
import json
import time

import httpx


class ProviderError(Exception):
    pass


def _post(url: str, body: dict, timeout: float, tries: int, wait: float) -> dict:
    last = None
    for i in range(tries):
        try:
            r = httpx.post(url, json=body, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            last = f"HTTP {r.status_code}: {r.text[:200]}"
        except httpx.HTTPError as e:
            last = repr(e)
        if i < tries - 1:
            time.sleep(wait * (i + 1))
    raise ProviderError(f"{url}: {last}")


class EmbeddingProvider:
    def __init__(self, url: str, model: str, timeout: float = 60.0, batch: int = 64, retry_wait: float = 2.0,
                 tries: int = 3):
        self.url, self.model, self.timeout, self.batch, self.retry_wait = url.rstrip("/"), model, timeout, batch, retry_wait
        self.tries = tries
        self.dim: int | None = None

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch):
            part = texts[i:i + self.batch]
            data = _post(f"{self.url}/v1/embeddings", {"model": self.model, "input": part}, self.timeout, self.tries,
                         self.retry_wait)["data"]
            out.extend(d["embedding"] for d in sorted(data, key=lambda d: d["index"]))
        if out:
            self.dim = len(out[0])
        return out


class RerankProvider:
    def __init__(self, url: str, model: str, timeout: float = 30.0):
        self.url, self.model, self.timeout = url.rstrip("/"), model, timeout

    def rerank(self, query: str, docs: list[str]) -> list[tuple[int, float]]:
        if not docs:
            return []
        res = _post(f"{self.url}/rerank", {"model": self.model, "query": query, "documents": docs}, self.timeout, 2, 1.0)
        return sorted(((r["index"], r["relevance_score"]) for r in res["results"]), key=lambda x: -x[1])


class LLMProvider:
    def __init__(self, url: str, model: str, timeout: float = 120.0):
        self.url, self.model, self.timeout = url.rstrip("/"), model, timeout

    def json(self, messages: list[dict], schema: dict, max_tokens: int = 800, temperature: float = 0.0) -> dict:
        body = {"model": self.model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature,
                "response_format": {"type": "json_schema", "json_schema": {"name": "out", "schema": schema}}}
        for _ in range(2):
            content = _post(f"{self.url}/v1/chat/completions", body, self.timeout, 2, 1.0)["choices"][0]["message"]["content"]
            try:
                return json.loads(content)
            except (json.JSONDecodeError, TypeError):
                continue
        raise ProviderError("LLM 응답이 JSON이 아님")

    def regex(self, messages: list[dict], pattern: str, max_tokens: int = 700, temperature: float = 0.0) -> str:
        """정규식으로 출력 형식을 고정한다. JSON 모드는 소형 모델이 키 사이 공백을 끝없이 내며 멈추는 일이 있어
        (2026-10-02 EXAONE-7.8B 실측) 줄 단위 형식을 쓴다."""
        import re

        body = {"model": self.model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature,
                "structured_outputs": {"regex": pattern}}
        for _ in range(2):
            content = (_post(f"{self.url}/v1/chat/completions", body, self.timeout, 2, 1.0)
                       ["choices"][0]["message"]["content"] or "").strip()
            if re.fullmatch(pattern, content):
                return content
        raise ProviderError("LLM 응답이 형식에 맞지 않음")
