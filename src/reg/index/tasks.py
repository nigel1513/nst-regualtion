"""색인 Airflow 진입점 (overview §2.6). 설정을 읽어 연결하고, ops.pipeline_run에 남기고, JSON dict를 돌려준다.
build는 게시하지 않는다: DAG가 build → gate → publish를 따로 부른다. 실패는 예외로 알린다."""
import os as _os
from pathlib import Path

import yaml

from reg.index.health import embed_ok
from reg.index.indexer import build_release
from reg.index.os import OpenSearch
from reg.index.release import gate_release, prune_releases, publish_release
from reg.platform.llm import EmbeddingProvider, RerankProvider
from reg.platform.runs import open_conn, task_run
from reg.platform.settings import ROOT, get_settings

# 새 색인의 첫 k-NN 검색은 HNSW 그래프를 메모리에 올리느라 60초를 넘길 수 있다 (실서버 2026-10-02 확인).
GATE_OS_TIMEOUT = 300.0


class GateFailed(RuntimeError):
    pass


def smoke_cases() -> list[dict]:
    """품질 게이트 고정 질의. REG_INDEX_SMOKE가 있으면 그 경로, 없으면 <repo>/config/index_smoke.yaml."""
    path = Path(_os.environ.get("REG_INDEX_SMOKE") or ROOT / "config/index_smoke.yaml")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or []


def embed_check() -> bool:
    """임베딩 서버가 5초 안에 응답하나. False면 DAG가 색인 태스크만 미룬다."""
    s = get_settings()
    with task_run("index.embed_check") as rec:
        ok = embed_ok(EmbeddingProvider(s.embed_url, s.embed_model, timeout=5, tries=1), limit=5.0)
        rec["ok"] = ok
    return ok


def build(force: bool = False, embed_pause: float | None = None) -> dict:
    """새 release 색인을 만든다(게시하지 않음). 변화 없는 날은 {"skipped": True, "release_id": 게시본 id}.
    embed_pause: 임베딩 요청 사이 쉬는 초 (GPU를 운영 질의와 나눠 쓴다). 없으면 REG_INDEX_EMBED_PAUSE, 기본 0."""
    s = get_settings()
    pause = float(_os.environ.get("REG_INDEX_EMBED_PAUSE") or 0) if embed_pause is None else embed_pause
    with task_run("index.build") as rec, open_conn() as conn:
        out = build_release(conn, OpenSearch(s.os_url), EmbeddingProvider(s.embed_url, s.embed_model, batch=32),
                            s.embed_model, publish=False, force=force, embed_pause=pause)
        rec.update(out)
    return out


def gate(release_id: int) -> dict:
    """품질 게이트. 실패하면 결과를 기록한 뒤 GateFailed. 이미 게시된 release는 통과."""
    s = get_settings()
    with task_run("index.gate") as rec, open_conn() as conn:
        out = gate_release(conn, OpenSearch(s.os_url, timeout=GATE_OS_TIMEOUT), EmbeddingProvider(s.embed_url, s.embed_model),
                           RerankProvider(s.rerank_url, s.rerank_model), int(release_id), smoke_cases())
        rec.update(out)
        if not out["passed"]:
            raise GateFailed(f"release {release_id} 품질 게이트 실패: {'; '.join(out['reasons'])}")
    return out


def publish(release_id: int) -> dict:
    """게이트를 통과한 release로 alias를 바꾼다. 두 번 불러도 already=True."""
    s = get_settings()
    with task_run("index.publish") as rec, open_conn() as conn:
        out = publish_release(conn, OpenSearch(s.os_url), int(release_id))
        rec.update(out)
    return out


def prune() -> dict:
    """게시본·직전 게시본·진행 중 빌드·alias 대상 밖의 release 색인을 지운다."""
    s = get_settings()
    with task_run("index.prune") as rec, open_conn() as conn:
        out = prune_releases(conn, OpenSearch(s.os_url))
        rec.update(out)
    return out
