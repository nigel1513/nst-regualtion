# M4a 하이브리드 검색 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 적재된 규정·법령 조문을 검색 단위(청크)로 나눠 공유 OpenSearch에 색인한다. 색인할 때 각 청크에 bge-m3 임베딩을 붙인다. 이를 바탕으로 다음 세 가지를 제공한다.
- BM25(nori)와 벡터를 섞은 하이브리드 검색
- 리랭크(bge-reranker-v2-m3)
- 임베딩 서버가 꺼졌을 때 BM25만으로 하는 검색

색인은 게시 버전(release) 단위로 만들고, 별칭(alias)을 바꿔서 원자적으로 공개한다(spec 7).

**Architecture:**
- **Provider** (`reg.llm`): vLLM 서버들의 OpenAI 호환 HTTP 엔드포인트를 감싼다.
  - 임베딩: `:8002/v1/embeddings`
  - 리랭크: `:8003/rerank`
  - 생성: `:8001/v1/chat/completions`
- **OpenSearch 클라이언트** (`reg.search.os`): httpx로 직접 호출한다. SDK는 쓰지 않는다(nst-nexus와 같은 방식).
- **청크 생성기** (`reg.search.chunks`): PostgreSQL의 버전별 조항을 청크로 바꾸는 순수 함수다.
- **색인기** (`reg.search.indexer`): 다음 순서로 동작한다.
  1. `release`를 BUILDING 상태로 만든다.
  2. 새 인덱스 `nais-regulations-r{N}`을 만든다.
  3. 같은 본문은 한 번만 임베딩해서 bulk로 넣는다.
  4. 확인 쿼리를 통과하면 별칭 `nais-regulations`를 원자적으로 바꾸고 PUBLISHED로 바꾼다.
- **검색 서비스** (`reg.search.service`): 하이브리드 질의(normalization-processor 검색 파이프라인), 필터(기관·현행/기준일·종류), 리랭크, 대체 경로를 맡는다.
- API `/api/v1/hsearch`와 웹 검색 화면을 이 서비스로 바꾼다.

**Tech Stack:**
- OpenSearch 2.19.1: nori, k-NN(lucene HNSW, cosinesimil), neural-search 하이브리드
- httpx, vLLM: bge-m3 1024차원, bge-reranker-v2-m3

**Spec:** `docs/superpowers/specs/2026-10-01-regulation-platform-design.md` (5.4 OpenSearch, 7 동기화·게시, 8.1 Provider, 8.2 4단계 검색, 8.5 장애 시 동작)

## Global Constraints

- **OpenSearch 접근**: 이 서버의 프로세스는 `http://127.0.0.1:21067`로 접근한다. 이 주소는 `infra/docker-compose.yml`의 `opensearch-proxy`가 `nais_default`의 `opensearch:9200`으로 중계한다.
- **이름 규칙**
  - 인덱스: `nais-regulations-r{release_id}`
  - 별칭: `nais-regulations`
  - 검색 파이프라인: `nais-regulations-hybrid`
  - 다른 이름의 인덱스는 건드리지 않는다.
- **Provider 기본 주소** (환경변수로 바꿀 수 있다)
  - `REG_EMBED_URL=http://192.168.0.2:8002`, 모델 `bge-m3`
  - `REG_RERANK_URL=http://192.168.0.2:8003`, 모델 `bge-reranker`
  - `REG_LLM_URL=http://192.168.0.2:8001`, 모델 `llm`
  - `REG_OS_URL=http://127.0.0.1:21067`
- **청크 단위 (spec 5.4)**
  - 기본은 조(article) 하나에 청크 하나다. 조 머리, 본문, 항·호·목을 모두 넣는다.
  - 1,200자를 넘으면 항 단위로 나누고, 각 청크 앞에 조 머리(`제N조(제목)`)를 붙인다.
  - 부칙·별표도 각각 청크 하나로 만들고, 1,200자에서 자른다.
  - `context_text`는 `규정명 > 장 제목 > 조 머리`다.
- **임베딩**: 배치 크기 64. 같은 `text` 해시는 한 번만 임베딩한다. 실패하면 3회 재시도하고, 그래도 안 되면 색인을 중단해서 게시하지 않는다.
- **하이브리드 결합**: min_max 정규화, arithmetic_mean, 가중치는 BM25 0.4 / 벡터 0.6이다. 후보 50건, 리랭크 뒤 기본 10건을 돌려준다.

## Review Focus

1. **색인 도중 실패**(임베딩 서버 중단, bulk 오류). 별칭은 이전 인덱스를 그대로 가리키고, release는 FAILED, 새 인덱스는 지운다. Task 4에서 테스트한다.
2. **임베딩 서버가 꺼진 상태의 검색.** 하이브리드 대신 BM25 결과를 돌려주고, 응답에 `mode: "bm25"`를 표시한다. Task 5에서 테스트한다.
3. **기준일 검색.** `as_of`가 있으면 `effective_from ≤ D < effective_to`(또는 effective_to 없음)인 청크만 나온다. 없으면 CURRENT만 나온다. Task 5에서 테스트한다.
4. **1,200자를 넘는 조문.** 항 단위로 나눌 때 내용이 빠지거나 겹치지 않아야 한다. 항이 없는 긴 조는 1,200자 단위로 자른다. Task 3에서 테스트한다.
5. **별칭이 아직 없는 첫 게시.** 별칭 생성과 제거가 오류 없이 처리되어야 한다. Task 4에서 테스트한다.

---

## File Structure

```
src/reg/llm.py                        # EmbeddingProvider, RerankProvider, LLMProvider, ProviderError
src/reg/search/__init__.py
src/reg/search/os.py                  # OpenSearch(url): put_pipeline, create_index, bulk, swap_alias, delete_index, search, alias_target
src/reg/search/mapping.py             # INDEX_BODY, PIPELINE_BODY, ALIAS, PIPELINE
src/reg/search/chunks.py              # Chunk, chunk_version(rows, title) -> list[Chunk]
src/reg/search/indexer.py             # build_release(conn, os, embedder, publish=True) -> dict
src/reg/search/service.py             # search(os, embedder, reranker, q, institution, as_of, kind, rerank, size) -> dict
src/reg/migrations/versions/0005_release.py
src/reg/api/app.py                    # (수정) /api/v1/hsearch
src/reg/cli.py                        # (수정) reg index build|status
src/reg/settings.py                   # (수정) os_url, embed_url, rerank_url, llm_url, 모델명
infra/docker-compose.yml              # (작성됨) opensearch-proxy
tests/conftest.py                     # (수정) os_container fixture
tests/test_llm.py tests/test_chunks.py tests/test_indexer.py tests/test_search.py
apps/web/src/app/search/page.tsx      # (수정) 하이브리드 검색 사용, 모드 표시
```

---

### Task 1: 설정과 Provider

**Files:**
- Modify: `src/reg/settings.py`, `.env.example`
- Create: `src/reg/llm.py`, `tests/test_llm.py`

**Interfaces:**
- Settings 필드
  - `os_url="http://127.0.0.1:21067"`
  - `embed_url="http://192.168.0.2:8002"`, `embed_model="bge-m3"`
  - `rerank_url="http://192.168.0.2:8003"`, `rerank_model="bge-reranker"`
  - `llm_url="http://192.168.0.2:8001"`, `llm_model="llm"`
- `class ProviderError(Exception)`
- `EmbeddingProvider(url, model, timeout=60.0, batch=64)`
  - `.embed(texts: list[str]) -> list[list[float]]`: 배치로 나눠 호출하고 순서를 유지한다. 실패하면 3회 재시도한 뒤 `ProviderError`
  - `.dim` 속성: 첫 호출 뒤에 정해진다.
- `RerankProvider(url, model, timeout=30.0)`
  - `.rerank(query: str, docs: list[str]) -> list[tuple[int, float]]`: 점수 내림차순으로 (원래 인덱스, 점수)를 돌려준다.
- `LLMProvider(url, model, timeout=120.0)`
  - `.json(messages: list[dict], schema: dict, max_tokens=800, temperature=0.0) -> dict`
  - `response_format={"type":"json_schema", "json_schema":{"name":"out","schema":schema}}`를 쓴다.
  - 결과를 `json.loads`한다. 파싱에 실패하면 한 번 다시 생성하고, 그래도 실패하면 `ProviderError`

- [ ] **Step 1: 실패하는 테스트**

```python
# tests/test_llm.py
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
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_llm.py -q` → FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: 구현**

`settings.py`의 `Settings`에 필드를 추가한다(위 Interfaces 값). `.env.example`에도 같은 키를 추가한다.

```python
# src/reg/llm.py
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
    def __init__(self, url: str, model: str, timeout: float = 60.0, batch: int = 64, retry_wait: float = 2.0):
        self.url, self.model, self.timeout, self.batch, self.retry_wait = url.rstrip("/"), model, timeout, batch, retry_wait
        self.dim: int | None = None

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch):
            part = texts[i:i + self.batch]
            data = _post(f"{self.url}/v1/embeddings", {"model": self.model, "input": part}, self.timeout, 3,
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
```

- [ ] **Step 4: 통과 확인 후 커밋** — `uv run pytest tests/test_llm.py -q` → 4 PASS

```bash
git add src/reg/llm.py src/reg/settings.py .env.example tests/test_llm.py
git commit -m "feat(llm): embedding, rerank and JSON-schema LLM providers"
```

---

### Task 2: OpenSearch 클라이언트, 매핑, release 테이블

**Files:**
- Create: `src/reg/search/__init__.py`, `src/reg/search/os.py`, `src/reg/search/mapping.py`, `src/reg/migrations/versions/0005_release.py`, `tests/test_os.py`
- Modify: `tests/conftest.py`
  - `os_url` 세션 픽스처를 추가한다. testcontainers `DockerContainer("nais-opensearch:2.19.1-nori")`를 쓰고, 환경변수는 `discovery.type=single-node`, `DISABLE_SECURITY_PLUGIN=true`, `DISABLE_INSTALL_DEMO_CONFIG=true`, `OPENSEARCH_JAVA_OPTS=-Xms512m -Xmx512m`, 포트는 9200이다. `_cluster/health`가 응답할 때까지 최대 90초 기다린다.
  - TRUNCATE 목록에 `regulation.release_item, regulation.release`를 추가한다.

**Interfaces:**
- `mapping.ALIAS = "nais-regulations"`, `mapping.PIPELINE = "nais-regulations-hybrid"`
- `mapping.index_body(dim: int) -> dict`, `mapping.PIPELINE_BODY`
- `OpenSearch(url)` 메서드
  - 관리: `.put_pipeline()`, `.create_index(name, dim)`, `.delete_index(name)`
  - 적재: `.bulk(name, docs: list[dict], id_field="chunk_id") -> int`(오류가 하나라도 있으면 `RuntimeError`), `.refresh(name)`, `.count(name) -> int`
  - 별칭: `.alias_target() -> str | None`, `.swap_alias(new_index) -> str | None`(이전 인덱스명)
  - 검색: `.search(body, pipeline: str | None = None, index=ALIAS) -> dict`
- `0005_release.py`
  - `release(id serial, state text CHECK BUILDING|PUBLISHED|RETIRED|FAILED, os_index text, embedding_model text, stats jsonb, error text, created_at, published_at)`
  - `release_item(release_id, work_version_id, PK)`

- [ ] **Step 1: 실패하는 테스트**

```python
# tests/test_os.py
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
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_os.py -q` → FAIL

- [ ] **Step 3: 구현**

```python
# src/reg/search/__init__.py
```

```python
# src/reg/search/mapping.py
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
```

```python
# src/reg/search/os.py
"""OpenSearch HTTP 클라이언트 (SDK 없이). 이 프로젝트 이름(nais-regulations*)만 다룬다."""
import json

import httpx

from reg.search.mapping import ALIAS, PIPELINE, PIPELINE_BODY, index_body


class OpenSearch:
    def __init__(self, url: str, timeout: float = 60.0):
        self.c = httpx.Client(base_url=url.rstrip("/"), timeout=timeout)

    def _ok(self, r: httpx.Response) -> dict:
        if r.status_code >= 300:
            raise RuntimeError(f"OpenSearch {r.request.method} {r.request.url.path}: {r.status_code} {r.text[:300]}")
        return r.json() if r.content else {}

    def put_pipeline(self) -> None:
        self._ok(self.c.put(f"/_search/pipeline/{PIPELINE}", json=PIPELINE_BODY))

    def create_index(self, name: str, dim: int) -> None:
        assert name.startswith(ALIAS + "-")
        self._ok(self.c.put(f"/{name}", json=index_body(dim)))

    def delete_index(self, name: str) -> None:
        assert name.startswith(ALIAS + "-")
        r = self.c.delete(f"/{name}")
        if r.status_code not in (200, 404):
            self._ok(r)

    def bulk(self, name: str, docs: list[dict], id_field: str = "chunk_id") -> int:
        if not docs:
            return 0
        lines = []
        for d in docs:
            lines.append(json.dumps({"index": {"_index": name, "_id": d[id_field]}}))
            lines.append(json.dumps(d, ensure_ascii=False))
        r = self._ok(self.c.post("/_bulk", content="\n".join(lines) + "\n",
                                 headers={"Content-Type": "application/x-ndjson"}))
        if r.get("errors"):
            first = next(i["index"]["error"] for i in r["items"] if "error" in i["index"])
            raise RuntimeError(f"bulk 오류: {first}")
        return len(docs)

    def refresh(self, name: str) -> None:
        self._ok(self.c.post(f"/{name}/_refresh"))

    def count(self, name: str) -> int:
        return self._ok(self.c.get(f"/{name}/_count"))["count"]

    def alias_target(self) -> str | None:
        r = self.c.get(f"/_alias/{ALIAS}")
        if r.status_code == 404:
            return None
        return next(iter(self._ok(r)), None)

    def swap_alias(self, new_index: str) -> str | None:
        old = self.alias_target()
        actions = [{"add": {"index": new_index, "alias": ALIAS}}]
        if old:
            actions.insert(0, {"remove": {"index": old, "alias": ALIAS}})
        self._ok(self.c.post("/_aliases", json={"actions": actions}))
        return old

    def search(self, body: dict, pipeline: str | None = None, index: str = ALIAS) -> dict:
        params = {"search_pipeline": pipeline} if pipeline else None
        return self._ok(self.c.post(f"/{index}/_search", json=body, params=params))
```

```python
# src/reg/migrations/versions/0005_release.py
"""게시 버전(release): 검색 색인과 답변 근거를 같은 스냅샷으로 묶는다 (spec 7)."""
from alembic import op

revision = "0005"
down_revision = "0004"


def upgrade() -> None:
    op.execute("""
CREATE TABLE regulation.release (
  id serial PRIMARY KEY,
  state text NOT NULL CHECK (state IN ('BUILDING', 'PUBLISHED', 'RETIRED', 'FAILED')),
  os_index text NOT NULL,
  embedding_model text NOT NULL,
  stats jsonb NOT NULL DEFAULT '{}',
  error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  published_at timestamptz
);
CREATE TABLE regulation.release_item (
  release_id int NOT NULL REFERENCES regulation.release(id) ON DELETE CASCADE,
  work_version_id text NOT NULL,
  PRIMARY KEY (release_id, work_version_id)
);""")


def downgrade() -> None:
    op.execute("DROP TABLE regulation.release_item; DROP TABLE regulation.release;")
```

`tests/conftest.py`에 다음을 추가한다.

```python
@pytest.fixture(scope="session")
def os_url():
    import time

    import httpx
    from testcontainers.core.container import DockerContainer

    c = (DockerContainer("nais-opensearch:2.19.1-nori").with_exposed_ports(9200)
         .with_env("discovery.type", "single-node").with_env("DISABLE_SECURITY_PLUGIN", "true")
         .with_env("DISABLE_INSTALL_DEMO_CONFIG", "true").with_env("OPENSEARCH_JAVA_OPTS", "-Xms512m -Xmx512m"))
    with c:
        url = f"http://{c.get_container_host_ip()}:{c.get_exposed_port(9200)}"
        for _ in range(90):
            try:
                if httpx.get(f"{url}/_cluster/health", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(1)
        yield url
```

- [ ] **Step 4: 통과 확인 후 커밋** — `uv run pytest tests/test_os.py -q` → 2 PASS

```bash
git add src/reg/search src/reg/migrations/versions/0005_release.py tests/conftest.py tests/test_os.py
git commit -m "feat(search): OpenSearch client, mapping with nori + knn, hybrid pipeline, release tables"
```

---

### Task 3: 청크 생성

**Files:**
- Create: `src/reg/search/chunks.py`, `tests/test_chunks.py`

**Interfaces:**
- `Chunk(chunk_id, version_id, work_id, path, path_label, text, context_text)` (dataclass)
- `MAX_CHARS = 1200`
- `chunk_version(version_id: str, work_id: str, title: str, provisions: list[dict]) -> list[Chunk]`
  - `provisions`는 문서 순서의 dict 목록이다. 키: `path`, `unit`, `label`, `heading`, `text`, `parent`
  - 청크 단위
    - 조(article)와 그 하위(항·호·목)를 묶어 청크 하나로 만든다.
    - 부칙(supplement와 그 supp_article)으로 청크 하나를 만든다.
    - 별표(annex)로 청크 하나를 만든다.
  - 본문 형식: `"{조 머리}\n{조 본문}\n{① 항 본문}\n{1. 호 본문}…"`
  - 길이가 `MAX_CHARS`를 넘을 때
    - 항이 있으면 항(과 그 하위) 단위로 나누고, 청크마다 조 머리를 붙인다.
    - 항이 없으면 `MAX_CHARS` 단위로 자른다. 경로는 `a5#1`, `a5#2`가 된다.
  - `chunk_id = f"{version_id}|{path}"`
  - `context_text = f"{title} > {장 머리} > {조 머리}"`

- [ ] **Step 1: 실패하는 테스트**

```python
# tests/test_chunks.py
from reg.search.chunks import MAX_CHARS, chunk_version


def P(path, unit, label, text="", heading=None, parent=None):
    return {"path": path, "unit": unit, "label": label, "heading": heading, "text": text, "parent": parent}


def test_article_with_paragraphs_is_one_chunk_with_context():
    provs = [P("c6", "chapter", "제6장", heading="보칙"),
             P("a27", "article", "제27조", heading="출장증빙의 제출", parent="c6"),
             P("a27.p1", "paragraph", "①", "출장자는 7일 이내에 증빙서를 제출하여야 한다.", parent="a27"),
             P("a27.p2", "paragraph", "②", "출장 증빙은 승차권 등으로 한다.", parent="a27")]
    cs = chunk_version("w@2024-01-17", "w", "여비규정", provs)
    assert [c.path for c in cs] == ["a27"]
    assert cs[0].text.startswith("제27조(출장증빙의 제출)") and "① 출장자는 7일" in cs[0].text and "② 출장 증빙은" in cs[0].text
    assert cs[0].context_text == "여비규정 > 제6장 보칙 > 제27조(출장증빙의 제출)"
    assert cs[0].chunk_id == "w@2024-01-17|a27"


def test_long_article_splits_by_paragraph_without_loss():
    body = "가" * 700
    provs = [P("a5", "article", "제5조", heading="활용"),
             P("a5.p1", "paragraph", "①", body, parent="a5"), P("a5.p2", "paragraph", "②", body, parent="a5"),
             P("a5.p2.i1", "item", "1.", "호 본문", parent="a5.p2")]
    cs = chunk_version("v", "w", "규정", provs)
    assert [c.path for c in cs] == ["a5.p1", "a5.p2"]
    assert all(c.text.startswith("제5조(활용)") for c in cs) and "1. 호 본문" in cs[1].text
    assert sum(c.text.count("가") for c in cs) == 1400


def test_long_article_without_paragraphs_is_cut():
    provs = [P("a9", "article", "제9조", "나" * (MAX_CHARS * 2 + 10), heading="긴 조")]
    cs = chunk_version("v", "w", "규정", provs)
    assert [c.path for c in cs] == ["a9#1", "a9#2", "a9#3"]
    assert sum(c.text.count("나") for c in cs) == MAX_CHARS * 2 + 10


def test_supplement_and_annex_chunks():
    provs = [P("a1", "article", "제1조", "목적.", heading="목적"),
             P("supp@2024-01-17", "supplement", "부칙", "이 규정은 2024년 1월 17일부터 시행한다."),
             P("annex1", "annex", "별표 제1호", "국내여비 지급기준표 …", heading="국내여비")]
    cs = chunk_version("v", "w", "규정", provs)
    assert [c.path for c in cs] == ["a1", "supp@2024-01-17", "annex1"]
    assert cs[1].text.startswith("부칙 2024. 1. 17.")
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_chunks.py -q` → FAIL

- [ ] **Step 3: 구현**

```python
# src/reg/search/chunks.py
"""검색 청크 생성 (spec 5.4): 조 단위, 길면 항 단위, 조 머리·장 제목을 문맥으로."""
from dataclasses import dataclass

MAX_CHARS = 1200
TOP = {"article", "supplement", "annex"}


@dataclass
class Chunk:
    chunk_id: str
    version_id: str
    work_id: str
    path: str
    path_label: str
    text: str
    context_text: str


def _head(p: dict) -> str:
    if p["unit"] == "supplement":
        d = p["path"].split("@")[1][:10] if "@" in p["path"] else ""
        return "부칙" + (" " + ". ".join(str(int(x)) for x in d.split("-")) + "." if d else "")
    return p["label"] + (f"({p['heading']})" if p.get("heading") else "")


def _line(p: dict) -> str:
    if p["unit"] in ("paragraph", "item", "subitem"):
        return f"{p['label']} {p['text']}".strip()
    if p["unit"] == "supp_article":
        return f"{_head(p)} {p['text']}".strip()
    return p["text"]


def chunk_version(version_id: str, work_id: str, title: str, provisions: list[dict]) -> list[Chunk]:
    kids: dict[str, list[dict]] = {}
    for p in provisions:
        kids.setdefault(p.get("parent") or "", []).append(p)

    def subtree(path: str) -> list[dict]:
        return [x for k in kids.get(path, []) for x in (k, *subtree(k["path"]))]

    chapter = None
    out: list[Chunk] = []

    def emit(path: str, label: str, head: str, body_lines: list[str]) -> None:
        ctx = " > ".join(x for x in (title, chapter, head) if x)
        text = "\n".join([head] + [b for b in body_lines if b])
        out.append(Chunk(f"{version_id}|{path}", version_id, work_id, path, label, text, ctx))

    for p in provisions:
        if p["unit"] == "chapter":
            chapter = _head(p) if not p.get("heading") else f"{p['label']} {p['heading']}"
            continue
        if p["unit"] not in TOP:
            continue
        head = _head(p)
        sub = subtree(p["path"])
        lines = [p["text"]] + [_line(s) for s in sub]
        full = "\n".join([head] + [x for x in lines if x])
        if len(full) <= MAX_CHARS:
            emit(p["path"], head, head, lines)
            continue
        paras = [s for s in kids.get(p["path"], []) if s["unit"] == "paragraph"]
        if paras:
            if p["text"]:
                paras_first = [p["text"]]
            else:
                paras_first = []
            for i, para in enumerate(paras):
                body = ([*paras_first] if i == 0 else []) + [_line(para)] + [_line(s) for s in subtree(para["path"])]
                emit(para["path"], f"{head} {para['label']}", head, body)
            continue
        body = "\n".join(x for x in lines if x)
        size = MAX_CHARS - len(head) - 1
        for n, i in enumerate(range(0, len(body), size), 1):
            emit(f"{p['path']}#{n}", head, head, [body[i:i + size]])
    return out
```

- [ ] **Step 4: 통과 확인 후 커밋** — `uv run pytest tests/test_chunks.py -q` → 4 PASS

```bash
git add src/reg/search/chunks.py tests/test_chunks.py
git commit -m "feat(search): provision chunking with context and long-article splitting"
```

---

### Task 4: 색인기 (release 빌드와 게시)

**Files:**
- Create: `src/reg/search/indexer.py`, `tests/test_indexer.py`
- Modify: `src/reg/cli.py` (`reg index build [--no-publish]`, `reg index status`)

**Interfaces:**
- `build_release(conn, os: OpenSearch, embedder, model_name: str, publish: bool = True) -> dict`
  1. `release`를 BUILDING으로 넣는다. 인덱스 이름은 `f"{ALIAS}-r{id}"`다.
  2. 모든 `work_version`(UNDATED 제외)의 조항을 `chunk_version`으로 청크로 만든다.
  3. 같은 text는 한 번만 임베딩한다.
  4. `put_pipeline`, `create_index(dim)`, 500건씩 bulk, refresh 순으로 진행한다.
  5. 확인: `count == len(chunks)`
  6. `publish`가 참이면 `swap_alias`를 하고, 이 release를 PUBLISHED, 이전 PUBLISHED는 RETIRED로 바꾼다. 이전 인덱스는 지우지 않고 보관한다(최근 2개).
  7. `release_item`에 포함된 버전을 기록한다.
  - 반환값: `{"release_id", "index", "chunks", "unique_texts", "versions"}`
  - 실패하면 release를 FAILED로 바꾸고 error를 기록한다. 만들던 인덱스는 지우고, 별칭은 그대로 둔다. 그런 다음 예외를 다시 던진다.
- 각 청크 문서의 필드: `release_id`, `institution`, `work_kind`, `title`, `effective_from`, `effective_to`, `version_state`, `embedding_model`

- [ ] **Step 1: 실패하는 테스트**

```python
# tests/test_indexer.py
from datetime import date

import pytest

from reg.process import process_once
from reg.search.indexer import build_release
from reg.search.os import OpenSearch
from reg.storage.blob import LocalBlobStore
from tests.test_process import FX, seed_alio


class FakeEmbedder:
    def __init__(self, fail=False):
        self.fail, self.calls, self.dim = fail, 0, 4

    def embed(self, texts):
        if self.fail:
            from reg.llm import ProviderError
            raise ProviderError("down")
        self.calls += len(texts)
        return [[float(len(t) % 7), 1.0, 0.5, 0.25] for t in texts]


@pytest.fixture
def loaded(conn, tmp_path):
    blob = LocalBlobStore(tmp_path)
    seed_alio(conn, blob, (FX / "samples" / "kasi-yeobi-339.pdf").read_bytes())
    process_once(conn, blob, today=date(2026, 10, 2))
    return conn


def test_build_and_publish(loaded, os_url):
    os = OpenSearch(os_url)
    for name in [os.alias_target()] if os.alias_target() else []:
        os.delete_index(name)
    st = build_release(loaded, os, FakeEmbedder(), "fake")
    assert st["chunks"] > 30 and os.alias_target() == st["index"]
    assert os.count(st["index"]) == st["chunks"]
    r = loaded.execute("SELECT state FROM regulation.release WHERE id = %s", (st["release_id"],)).fetchone()
    assert r["state"] == "PUBLISHED"
    st2 = build_release(loaded, os, FakeEmbedder(), "fake")
    assert os.alias_target() == st2["index"]
    states = [x["state"] for x in loaded.execute("SELECT state FROM regulation.release ORDER BY id").fetchall()]
    assert states[-2:] == ["RETIRED", "PUBLISHED"]


def test_failed_build_keeps_alias(loaded, os_url):
    os = OpenSearch(os_url)
    before = build_release(loaded, os, FakeEmbedder(), "fake")["index"]
    with pytest.raises(Exception):
        build_release(loaded, os, FakeEmbedder(fail=True), "fake")
    assert os.alias_target() == before
    assert loaded.execute("SELECT state FROM regulation.release ORDER BY id DESC LIMIT 1").fetchone()["state"] == "FAILED"
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_indexer.py -q` → FAIL

- [ ] **Step 3: 구현**

```python
# src/reg/search/indexer.py
"""게시 버전 빌드: 청크 → 임베딩(중복 제거) → 새 인덱스 → 확인 → 별칭 전환 (spec 7)."""
import hashlib
import json

from reg.search.chunks import chunk_version
from reg.search.mapping import ALIAS
from reg.search.os import OpenSearch

BULK = 500


def _versions(conn) -> list[dict]:
    return conn.execute(
        "SELECT v.id, v.work_id, v.title, v.effective_from, v.effective_to, v.version_state, w.kind,"
        " i.code AS institution FROM regulation.work_version v JOIN regulation.work w ON w.id = v.work_id"
        " LEFT JOIN regulation.institution i ON i.id = w.institution_id WHERE v.version_state <> 'UNDATED'"
        " ORDER BY v.id").fetchall()


def _provisions(conn, version_id: str) -> list[dict]:
    return conn.execute(
        "SELECT pv.path, pv.unit, pv.number_label AS label, pv.heading, pv.text, pv.parent_path AS parent"
        " FROM regulation.version_provision vp JOIN regulation.provision_version pv ON pv.id = vp.provision_version_id"
        " WHERE vp.work_version_id = %s ORDER BY vp.ord", (version_id,)).fetchall()


def build_release(conn, os: OpenSearch, embedder, model_name: str, publish: bool = True) -> dict:
    rid = conn.execute("INSERT INTO regulation.release (state, os_index, embedding_model) VALUES ('BUILDING', '', %s)"
                       " RETURNING id", (model_name,)).fetchone()["id"]
    index = f"{ALIAS}-r{rid}"
    conn.execute("UPDATE regulation.release SET os_index = %s WHERE id = %s", (index, rid))
    conn.commit()
    created = False
    try:
        versions = _versions(conn)
        docs, texts = [], {}
        for v in versions:
            for c in chunk_version(v["id"], v["work_id"], v["title"], _provisions(conn, v["id"])):
                h = hashlib.sha256(c.text.encode()).hexdigest()
                texts.setdefault(h, c.text)
                docs.append((h, {"chunk_id": c.chunk_id, "release_id": str(rid), "work_id": c.work_id,
                                 "version_id": c.version_id, "path": c.path, "path_label": c.path_label,
                                 "institution": v["institution"], "work_kind": v["kind"], "title": v["title"],
                                 "text": c.text, "context_text": c.context_text,
                                 "effective_from": v["effective_from"].isoformat() if v["effective_from"] else None,
                                 "effective_to": v["effective_to"].isoformat() if v["effective_to"] else None,
                                 "version_state": v["version_state"], "embedding_model": model_name}))
        keys = list(texts)
        vecs = dict(zip(keys, embedder.embed([texts[k] for k in keys])))
        dim = len(next(iter(vecs.values()))) if vecs else (embedder.dim or 1024)
        os.put_pipeline()
        os.create_index(index, dim)
        created = True
        batch = []
        for h, d in docs:
            d["embedding"] = vecs[h]
            batch.append(d)
            if len(batch) >= BULK:
                os.bulk(index, batch)
                batch = []
        os.bulk(index, batch)
        os.refresh(index)
        if os.count(index) != len(docs):
            raise RuntimeError(f"색인 건수 불일치 {os.count(index)} != {len(docs)}")
        for v in versions:
            conn.execute("INSERT INTO regulation.release_item (release_id, work_version_id) VALUES (%s, %s)",
                         (rid, v["id"]))
        stats = {"chunks": len(docs), "unique_texts": len(keys), "versions": len(versions)}
        if publish:
            os.swap_alias(index)
            conn.execute("UPDATE regulation.release SET state = 'RETIRED' WHERE state = 'PUBLISHED'")
            conn.execute("UPDATE regulation.release SET state = 'PUBLISHED', published_at = now(), stats = %s"
                         " WHERE id = %s", (json.dumps(stats), rid))
        else:
            conn.execute("UPDATE regulation.release SET stats = %s WHERE id = %s", (json.dumps(stats), rid))
        conn.commit()
        return {"release_id": rid, "index": index, **stats}
    except Exception as e:
        conn.rollback()
        if created:
            os.delete_index(index)
        conn.execute("UPDATE regulation.release SET state = 'FAILED', error = %s WHERE id = %s",
                     (f"{type(e).__name__}: {e}"[:2000], rid))
        conn.commit()
        raise
```

`cli.py`에 추가한다.

```python
index = typer.Typer(no_args_is_help=True, help="검색 색인(게시 버전)")
app.add_typer(index, name="index")


@index.command("build")
def index_build(no_publish: bool = typer.Option(False, "--no-publish")) -> None:
    from reg.llm import EmbeddingProvider
    from reg.search.indexer import build_release
    from reg.search.os import OpenSearch

    s = get_settings()
    conn = connect(s.database_url)
    st = build_release(conn, OpenSearch(s.os_url), EmbeddingProvider(s.embed_url, s.embed_model), s.embed_model,
                       publish=not no_publish)
    typer.echo(f"release {st}")


@index.command("status")
def index_status() -> None:
    from reg.search.os import OpenSearch

    s = get_settings()
    conn = connect(s.database_url)
    for r in conn.execute("SELECT id, state, os_index, stats, created_at FROM regulation.release ORDER BY id DESC LIMIT 5"):
        typer.echo(f"{r['id']} {r['state']} {r['os_index']} {r['stats']}")
    typer.echo(f"alias → {OpenSearch(s.os_url).alias_target()}")
```

- [ ] **Step 4: 통과 확인 후 커밋** — `uv run pytest tests/test_indexer.py -q` → 2 PASS

```bash
git add src/reg/search/indexer.py src/reg/cli.py tests/test_indexer.py
git commit -m "feat(search): release build with deduplicated embeddings and atomic alias swap"
```

---

### Task 5: 검색 서비스와 API

**Files:**
- Create: `src/reg/search/service.py`, `tests/test_search.py`
- Modify: `src/reg/api/app.py`
  - `create_app`에 `search_deps: dict | None = None`을 추가한다(`os`, `embedder`, `reranker`).
  - 엔드포인트 `GET /api/v1/hsearch`를 추가한다.

**Interfaces:**
- `search(os, embedder, reranker, q: str, institution: str | None = None, as_of: str | None = None, kind: str | None = None, rerank: bool = True, size: int = 10) -> dict`
  - 반환값: `{"mode": "hybrid"|"bm25", "reranked": bool, "release_id": str | None, "hits": [{chunk_id, work_id, version_id, path, path_label, title, institution, text, score}]}`
  - 필터
    - `as_of`가 있으면 `effective_from ≤ as_of`이고 (`effective_to > as_of` 또는 effective_to 없음)
    - `as_of`가 없으면 `version_state = CURRENT`
    - `institution`이 있으면 `institution = X`이거나 법령(`work_kind`가 INTERNAL_REG가 아님)
    - `kind=law`이면 법령만
  - BM25 질의: `multi_match {query, fields: [text^2, path_label^2, title, context_text]}`
  - 하이브리드: embedder로 질의 벡터를 만든 뒤 `hybrid {queries: [bm25, knn {embedding: {vector, k: 50, filter}}]}` 질의를 `search_pipeline=PIPELINE`으로 보낸다.
  - embedder가 `ProviderError`를 내면 BM25로 바꾼다(`mode="bm25"`).
  - 후보 50건 → `rerank`가 참이고 reranker가 동작하면 리랭크 순서로 `size`건을 고른다. reranker가 실패하면 원래 순서를 쓰고 `reranked=False`다.
- API: `GET /api/v1/hsearch?q=&institution=&as_of=&kind=&rerank=true&size=10`
  - `q`는 2자 이상이어야 한다. 아니면 422.
  - 별칭(색인)이 없으면 503 `{"detail": "검색 색인이 아직 없습니다"}`

- [ ] **Step 1: 실패하는 테스트**

```python
# tests/test_search.py
import pytest

from reg.llm import ProviderError
from reg.search.indexer import build_release
from reg.search.os import OpenSearch
from reg.search.service import search
from tests.test_indexer import FakeEmbedder, loaded  # noqa: F401  (fixture 재사용)


class FakeReranker:
    def rerank(self, q, docs):
        return sorted(((i, 1.0 if "7일" in d else 0.0) for i, d in enumerate(docs)), key=lambda x: -x[1])


class DownEmbedder(FakeEmbedder):
    def embed(self, texts):
        raise ProviderError("down")


@pytest.fixture
def indexed(loaded, os_url):
    os = OpenSearch(os_url)
    build_release(loaded, os, FakeEmbedder(), "fake")
    return os


def test_hybrid_with_rerank_finds_deadline_article(indexed):
    r = search(indexed, FakeEmbedder(), FakeReranker(), "출장 증빙 제출 기한", institution="KASI")
    assert r["mode"] == "hybrid" and r["reranked"] and r["hits"][0]["path"].startswith("a27")
    assert all(h["institution"] in ("KASI", None) for h in r["hits"])


def test_bm25_fallback_when_embedder_down(indexed):
    r = search(indexed, DownEmbedder(), None, "증빙서", rerank=False)
    assert r["mode"] == "bm25" and r["hits"]


def test_as_of_filters_versions(indexed):
    assert search(indexed, FakeEmbedder(), None, "증빙서", as_of="1990-01-01", rerank=False)["hits"] == []
    assert search(indexed, FakeEmbedder(), None, "증빙서", as_of="2025-01-01", rerank=False)["hits"]
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_search.py -q` → FAIL

- [ ] **Step 3: 구현**

```python
# src/reg/search/service.py
"""하이브리드 검색 (spec 8.2 4단계, 8.5 장애 시 동작)."""
from reg.llm import ProviderError
from reg.search.mapping import PIPELINE

CANDIDATES = 50
FIELDS = ["text^2", "path_label^2", "title", "context_text"]


def _filters(institution: str | None, as_of: str | None, kind: str | None) -> list[dict]:
    f: list[dict] = []
    if as_of:
        f.append({"range": {"effective_from": {"lte": as_of}}})
        f.append({"bool": {"should": [{"range": {"effective_to": {"gt": as_of}}},
                                      {"bool": {"must_not": {"exists": {"field": "effective_to"}}}}],
                           "minimum_should_match": 1}})
    else:
        f.append({"term": {"version_state": "CURRENT"}})
    if kind == "law":
        f.append({"bool": {"must_not": {"term": {"work_kind": "INTERNAL_REG"}}}})
    if institution:
        f.append({"bool": {"should": [{"term": {"institution": institution}},
                                      {"bool": {"must_not": {"term": {"work_kind": "INTERNAL_REG"}}}}],
                           "minimum_should_match": 1}})
    return f


def search(os, embedder, reranker, q: str, institution: str | None = None, as_of: str | None = None,
           kind: str | None = None, rerank: bool = True, size: int = 10) -> dict:
    flt = _filters(institution, as_of, kind)
    bm25 = {"bool": {"must": {"multi_match": {"query": q, "fields": FIELDS}}, "filter": flt}}
    mode = "hybrid"
    try:
        vec = embedder.embed([q])[0]
        body = {"size": CANDIDATES, "_source": {"excludes": ["embedding"]},
                "query": {"hybrid": {"queries": [bm25, {"knn": {"embedding": {
                    "vector": vec, "k": CANDIDATES, "filter": {"bool": {"filter": flt}}}}}]}}}
        res = os.search(body, pipeline=PIPELINE)
    except ProviderError:
        mode = "bm25"
        res = os.search({"size": CANDIDATES, "_source": {"excludes": ["embedding"]}, "query": bm25})
    hits = [{**{k: h["_source"].get(k) for k in ("chunk_id", "work_id", "version_id", "path", "path_label", "title",
                                                  "institution", "text", "release_id")}, "score": h["_score"]}
            for h in res["hits"]["hits"]]
    reranked = False
    if rerank and reranker and hits:
        try:
            order = reranker.rerank(q, [h["text"] for h in hits])
            hits = [{**hits[i], "rerank_score": s} for i, s in order]
            reranked = True
        except ProviderError:
            pass
    release = hits[0].pop("release_id") if hits else None
    for h in hits[1:]:
        h.pop("release_id", None)
    return {"mode": mode, "reranked": reranked, "release_id": release, "hits": hits[:size]}
```

`app.py`: `create_app(dsn, blob, search_deps=None)`가 `app.state.search = search_deps or {}`를 저장한다. 엔드포인트를 추가한다.

```python
    @app.get("/api/v1/hsearch")
    def hsearch(q: str = Query(..., min_length=2), institution: str | None = None, as_of: date | None = None,
                kind: str | None = Query(None, pattern="^(law|reg)$"), rerank: bool = True, size: int = Query(10, le=50)):
        from reg.search.service import search as hybrid

        deps = app.state.search
        if not deps or deps["os"].alias_target() is None:
            raise HTTPException(503, "검색 색인이 아직 없습니다")
        return hybrid(deps["os"], deps["embedder"], deps.get("reranker"), q, institution,
                      as_of.isoformat() if as_of else None, kind, rerank, size)
```

`cli.py`의 `api_cmd`에서 `search_deps`를 만들어 넘긴다.

```python
    from reg.llm import EmbeddingProvider, RerankProvider
    from reg.search.os import OpenSearch

    s = get_settings()
    deps = {"os": OpenSearch(s.os_url), "embedder": EmbeddingProvider(s.embed_url, s.embed_model),
            "reranker": RerankProvider(s.rerank_url, s.rerank_model)}
    uvicorn.run(create_app(s.database_url, _blob(), deps), host=host, port=port, log_level="info")
```

- [ ] **Step 4: 통과 확인 후 커밋** — `uv run pytest -q` → 전체 PASS

```bash
git add src/reg/search/service.py src/reg/api/app.py src/reg/cli.py tests/test_search.py
git commit -m "feat(search): hybrid BM25+vector search with rerank and BM25 fallback; /api/v1/hsearch"
```

---

### Task 6: 웹 검색 화면 전환과 실색인

**Files:**
- Modify: `apps/web/src/app/search/page.tsx`, `apps/web/src/lib/api.ts`

**Interfaces:**
- 검색 화면은 먼저 `/api/v1/hsearch`(`institution`, `as_of`)를 부른다.
- 색인이 없어서 503이면 기존 `/api/v1/search`(키워드)로 바꾼다.
- 결과 위에 모드 칩을 보여준다: "하이브리드 + 재정렬", "키워드(임베딩 서버 응답 없음)", "키워드".
- 결과 카드: 규정명, 조 머리(`path_label`), 본문 앞 160자. 누르면 해당 조로 이동한다(`path`의 `#n`은 뗀다).

- [ ] **Step 1: 구현**
  - `api.ts`에 타입 `HHit`(`chunk_id`, `work_id`, `version_id`, `path`, `path_label`, `title`, `institution`, `text`, `score`)와 `HSearch`(`mode`, `reranked`, `release_id`, `hits`)를 추가한다.
  - `apiGet`은 503을 예외로 던지므로, 검색 화면은 `try/catch`로 503일 때 키워드 검색을 호출한다.
  - 화면은 위 Interfaces를 따르고, 기존 키워드 결과 렌더링을 대체 경로에서 그대로 재사용한다.

- [ ] **Step 2: 실DB 색인과 확인**

```bash
set -a; . ./.env; set +a
uv run reg db upgrade
uv run reg index build
uv run reg index status
bash scripts/run-dev.sh
curl -s "localhost:21061/api/v1/hsearch?q=%EC%B6%9C%EC%9E%A5%20%EC%A6%9D%EB%B9%99%20%EC%A0%9C%EC%B6%9C%20%EA%B8%B0%ED%95%9C&institution=KASI" | head -c 400
```

Expected:
- `index build`가 `chunks > 10000`을 출력한다.
- `status`에서 별칭이 새 인덱스를 가리킨다.
- `hsearch` 결과의 `mode`가 `hybrid`, `reranked`가 true이고, 상위에 천문연 여비규정 제27조가 나온다.

- [ ] **Step 3: 커밋**

```bash
git add apps/web/src
git commit -m "feat(web): search page uses hybrid search with keyword fallback"
```

---

## Self-Review 결과

**스펙 대응**

| 스펙 | 반영 위치 |
|---|---|
| 5.4 매핑·청크·과거 버전 동일 인덱스 | Task 2, 3 |
| 7 게시 버전·별칭 원자 전환·실패 시 유지 | Task 4 |
| 8.1 Provider 세 가지 | Task 1 |
| 8.2 4단계 하이브리드+리랭크 | Task 5 |
| 8.5 임베딩·리랭커 장애 | Task 5 |

**다음 단계로 넘기는 항목**
- 질의 분석, 근거 확장, 답변 생성·검증 → M4b
- 증분 색인(변경된 work만) → M4b 이후. 지금은 전체를 다시 빌드한다. 수십 초에서 수 분이 걸린다.
- 동의어 사전 → M6

**타입 일치**: `Chunk` 필드, 인덱스 문서 필드, `search()` 반환 키, API 응답, 웹 타입이 서로 같다.
