"""config/sources/lawgo.yaml 읽기. `law:`는 법령 범위(scope.py). 옛 형식(이름 목록)은 promote.laws로 읽는다 (판정 R10)."""
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from reg.platform.settings import ROOT

DEFAULT_PATH = ROOT / "config" / "sources" / "lawgo.yaml"


LAW_SUFFIXES = ["법", "법률", "시행령", "시행규칙", "영", "에 관한 규정"]
LAW_EXCLUDE = ["법", "법률", "시행령", "시행규칙", "영", "동법", "동 법", "같은 법", "이 법", "본법", "동법 시행령",
               "같은 법 시행령", "동법 시행규칙", "같은 법 시행규칙", "동 시행령", "같은 영", "이 영", "동령"]
LAW_EXCLUDE_SUFFIXES = ["방법"]
LAW_CHILDREN = ["시행령", "시행규칙"]


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
    law_include: list[str] = field(default_factory=list)
    law_children: list[str] = field(default_factory=lambda: list(LAW_CHILDREN))
    law_max_targets: int = 4000
    law_min_citations: int = 1
    law_cited_suffixes: list[str] = field(default_factory=lambda: list(LAW_SUFFIXES))
    law_cited_exclude: list[str] = field(default_factory=lambda: list(LAW_EXCLUDE))
    law_cited_exclude_suffixes: list[str] = field(default_factory=lambda: list(LAW_EXCLUDE_SUFFIXES))


def load_config(path: Path | None = None) -> LawgoConfig:
    p = Path(path) if path else DEFAULT_PATH
    if not p.exists():
        return LawgoConfig()
    d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if isinstance(d, list):
        return LawgoConfig(promote_laws=[str(x) for x in d])
    pr, ad, an, sy, lw = (d.get(k) or {} for k in ("promote", "admrul", "annex", "sync", "law"))
    ci = lw.get("cited") or {}
    return LawgoConfig(
        promote_laws=[str(x) for x in pr.get("laws") or []], promote_admruls=[str(x) for x in pr.get("admruls") or []],
        admrul_include=[str(x) for x in ad.get("include") or []], buffer_days=int(sy.get("buffer_days", 7)),
        page_size=int(sy.get("page_size", 100)), annex_store_pdf=bool(an.get("store_pdf", True)),
        annex_body_limit=int(an.get("body_limit_per_run", 2000)),
        abolish_min_ratio=float(sy.get("abolish_min_ratio", 0.95)),
        law_include=[str(x) for x in lw.get("include") or []],
        law_children=[str(x) for x in lw.get("children") or LAW_CHILDREN],
        law_max_targets=int(lw.get("max_targets", 4000)), law_min_citations=int(ci.get("min_citations", 1)),
        law_cited_suffixes=[str(x) for x in ci.get("suffixes") or LAW_SUFFIXES],
        law_cited_exclude=[str(x) for x in ci.get("exclude") or LAW_EXCLUDE],
        law_cited_exclude_suffixes=[str(x) for x in ci.get("exclude_suffixes") or LAW_EXCLUDE_SUFFIXES])
