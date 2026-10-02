"""config/sources/lawgo.yaml 읽기. 옛 형식(이름 목록)은 promote.laws로 읽는다 (판정 R10)."""
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from reg.platform.settings import ROOT

DEFAULT_PATH = ROOT / "config" / "sources" / "lawgo.yaml"


@dataclass
class LawgoConfig:
    promote_laws: list[str] = field(default_factory=list)
    promote_admruls: list[str] = field(default_factory=list)
    admrul_include: list[str] = field(default_factory=list)
    buffer_days: int = 7
    page_size: int = 100
    annex_store_pdf: bool = True
    annex_body_limit: int = 2000
    abolish_min_ratio: float = 0.95


def load_config(path: Path | None = None) -> LawgoConfig:
    p = Path(path) if path else DEFAULT_PATH
    if not p.exists():
        return LawgoConfig()
    d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if isinstance(d, list):
        return LawgoConfig(promote_laws=[str(x) for x in d])
    pr, ad, an, sy = (d.get(k) or {} for k in ("promote", "admrul", "annex", "sync"))
    return LawgoConfig(
        promote_laws=[str(x) for x in pr.get("laws") or []], promote_admruls=[str(x) for x in pr.get("admruls") or []],
        admrul_include=[str(x) for x in ad.get("include") or []], buffer_days=int(sy.get("buffer_days", 7)),
        page_size=int(sy.get("page_size", 100)), annex_store_pdf=bool(an.get("store_pdf", True)),
        annex_body_limit=int(an.get("body_limit_per_run", 2000)),
        abolish_min_ratio=float(sy.get("abolish_min_ratio", 0.95)))
