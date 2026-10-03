"""규정 주제(regulation.work_topic, 마이그레이션 0011) 읽기 도우미 (서비스 UI 개편 §4).

work_topic(work_id, topic, score, method, rank)은 reg topics classify가 채운다. 주제 id와 라벨은 config/topics.yaml
(topics: [{id, label, …}])이 정본이다. 테이블이 없으면(옛 DB) 주제는 조용히 빠진다(None)."""
from functools import lru_cache
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[3] / "config" / "topics.yaml"


@lru_cache(maxsize=1)
def _config_labels() -> dict[str, str]:
    if not CONFIG.exists():
        return {}
    try:
        import yaml

        data = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    topics = data.get("topics", data) if isinstance(data, dict) else data
    out: dict[str, str] = {}
    if isinstance(topics, dict):
        for k, v in topics.items():
            out[str(k)] = str(v.get("label") or v.get("name") or k) if isinstance(v, dict) else str(v)
    elif isinstance(topics, list):
        for t in topics:
            if isinstance(t, dict):
                key = t.get("key") or t.get("id") or t.get("code")
                if key:
                    out[str(key)] = str(t.get("label") or t.get("name") or key)
    return out


def topic_label(key: str) -> str:
    return _config_labels().get(key) or key


def has_topics(conn) -> bool:
    return conn.execute("SELECT to_regclass('regulation.work_topic') IS NOT NULL AS ok").fetchone()["ok"]


def work_topics(conn) -> dict[str, list[str]] | None:
    """규정 → 주제 키 목록. 테이블이 없거나 모양이 다르면 None."""
    if not has_topics(conn):
        return None
    try:
        rows = conn.execute("SELECT work_id, topic FROM regulation.work_topic ORDER BY work_id, topic").fetchall()
    except Exception:
        conn.rollback()
        return None
    out: dict[str, list[str]] = {}
    for r in rows:
        out.setdefault(r["work_id"], []).append(r["topic"])
    return out
