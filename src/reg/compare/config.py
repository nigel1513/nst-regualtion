"""기관 비교 설정 (config/topics.yaml): 주제와 주제별 비교 항목 (서비스 UI 개편 spec §4)."""
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from reg.platform.settings import ROOT

NORMS = ("duration", "won", "boolean", "text")


@dataclass(frozen=True)
class Topic:
    id: str
    label: str
    description: str
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class Item:
    id: str
    topic: str
    label: str
    query: str
    ask: str
    unit: str
    norm: str


@dataclass
class Config:
    topics: list[Topic]
    items: dict[str, list[Item]] = field(default_factory=dict)

    def topic(self, topic_id: str) -> Topic:
        return next(t for t in self.topics if t.id == topic_id)

    def item(self, topic_id: str, item_id: str) -> Item:
        return next(i for i in self.items[topic_id] if i.id == item_id)

    def has_topic(self, topic_id: str) -> bool:
        return any(t.id == topic_id for t in self.topics)


def path() -> Path:
    return Path(os.environ.get("REG_TOPICS") or ROOT / "config/topics.yaml")


def parse(data: dict) -> Config:
    topics = [Topic(t["id"], t["label"], t["description"], tuple(t.get("keywords") or ())) for t in data["topics"]]
    ids = {t.id for t in topics}
    items: dict[str, list[Item]] = {}
    for tid, rows in (data.get("items") or {}).items():
        if tid not in ids:
            raise ValueError(f"비교 항목의 주제가 없다: {tid}")
        items[tid] = []
        for r in rows:
            if r["norm"] not in NORMS:
                raise ValueError(f"정규화 규칙이 잘못됐다: {tid}.{r['id']} {r['norm']}")
            items[tid].append(Item(r["id"], tid, r["label"], r["query"], r["ask"], r.get("unit") or "", r["norm"]))
    return Config(topics, items)


@lru_cache(maxsize=4)
def _load(p: str, mtime: float) -> Config:
    return parse(yaml.safe_load(Path(p).read_text(encoding="utf-8")))


def load(p: Path | None = None) -> Config:
    p = p or path()
    return _load(str(p), p.stat().st_mtime)
