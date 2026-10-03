"""배치: 주제 분류(reg topics classify)와 비교값 만들기(reg compare build). CLI·Airflow 공통."""
import time
from collections.abc import Callable

from reg.compare import store
from reg.compare.classify import WorkText, classify
from reg.compare.config import Config
from reg.compare.extract import Cell, candidates, extract
from reg.index.cache import embed_cached, text_hash


def cached_embed(conn, embedder, model: str) -> Callable[[list[str]], list[list[float]]]:
    """ops.embedding_cache를 거치는 임베딩 (색인 빌드와 같은 캐시). 읽기 전용 실행에는 embedder.embed를 그대로 쓴다."""
    def embed(texts: list[str]) -> list[list[float]]:
        hs = [text_hash(t) for t in texts]
        got, _ = embed_cached(conn, embedder, model, dict(zip(hs, texts)))
        return [got[h] for h in hs]
    return embed


def classify_works(conn, cfg: Config, embed, works: list[WorkText], replace_all: bool = False,
                   dry_run: bool = False, exemplars: list[WorkText] | None = None) -> dict:
    """exemplars: 주제 벡터용 규정 모음. 일부(새 규정)만 분류할 때도 전체 현행 규정을 넘긴다(임베딩은 캐시)."""
    result = classify(works, cfg.topics, embed, exemplars=exemplars)
    stats: dict = {"works": len(works), "by_method": {}, "by_topic": {}}
    for got in result.values():
        stats["by_method"][got[0][2]] = stats["by_method"].get(got[0][2], 0) + 1
        for t, _, _ in got:
            stats["by_topic"][t] = stats["by_topic"].get(t, 0) + 1
    if not dry_run:
        stats["rows"] = store.save_topics(conn, result, replace_all=replace_all)
    stats["result"] = result
    return stats


def build_topic(deps: dict, cfg: Config, topic: str, works_by_inst: dict[str, list[str]], insts: list[str],
                on_cell: Callable[[Cell], None] | None = None) -> list[Cell]:
    """기관 × 항목 칸을 만든다. deps: os, embedder, reranker, llm. 그 주제 규정이 없는 기관은 LLM 없이 absent."""
    cells = []
    for inst in insts:
        works = works_by_inst.get(inst, [])
        for item in cfg.items.get(topic, []):
            if works:
                cands = candidates(deps["os"], deps["embedder"], deps.get("reranker"), item, works)
                cell = extract(deps["llm"], item, inst, cands)
            else:
                cell = Cell(topic, item.id, inst, "absent", note="주제 규정 없음")
            cells.append(cell)
            if on_cell:
                on_cell(cell)
    return cells


def build(conn, deps: dict, cfg: Config, topics: list[str] | None = None, insts: list[str] | None = None,
          dry_run: bool = False, on_cell: Callable[[Cell], None] | None = None) -> dict:
    """주제(기본: 비교 항목이 있는 모든 주제) × 기관(기본: 활성 기관 전부)의 비교값을 만들고 저장한다."""
    t0 = time.monotonic()
    topics = topics or list(cfg.items)
    all_insts = [r["code"] for r in store.institutions(conn)]
    insts = [i for i in all_insts if i in insts] if insts else all_insts
    stats = {"topics": topics, "institutions": len(insts), "cells": 0, "values": 0, "absent": 0}
    for topic in topics:
        by_inst = store.topic_works(conn, topic)
        conn.rollback()     # LLM을 기다리는 동안 트랜잭션을 열어 두지 않는다
        cells = build_topic(deps, cfg, topic, by_inst, insts, on_cell)
        stats["cells"] += len(cells)
        stats["values"] += sum(c.method == "llm" for c in cells)
        stats["absent"] += sum(c.method == "absent" for c in cells)
        if not dry_run:
            store.save_cells(conn, cells)
    stats["seconds"] = round(time.monotonic() - t0, 1)
    return stats
