"""앱 계층 조립: 출처 처리기 등록, 하위 CLI 목록, 마이그레이션 위치."""
from reg.core.ingest import registry


def register_sources() -> None:
    from reg.sources import alio, lawgo

    for h in alio.HANDLERS + lawgo.HANDLERS:
        registry.register(h)


def subcommands() -> list:
    from reg.alerts.cli import alerts, owners
    from reg.compare.cli import compare_app, topics_app  # UI 개편 §4 기관 비교
    from reg.core.annex_cli import annex
    from reg.core.quality_cli import quality
    from reg.core.refs_cli import refs
    from reg.graph.cli import graph
    from reg.index.cli import index
    from reg.ocr.cli import ocr  # M6-5
    from reg.ops.cli import app as ops  # M6-3
    from reg.search.cli import search_app  # M7-S
    from reg.sources.alio.cli import alio
    from reg.sources.lawgo.cli import law

    return [("alio", alio), ("law", law), ("index", index), ("graph", graph), ("alerts", alerts), ("owners", owners),
            ("ocr", ocr), ("ops", ops), ("quality", quality), ("annex", annex), ("refs", refs),
            ("search", search_app), ("topics", topics_app), ("compare", compare_app)]


def process_command():
    from reg.core.cli import process_cmd

    return process_cmd


def migration_locations() -> list:
    from reg.core.ingest.migrations_location import MIGRATIONS as core
    from reg.sources import alio, lawgo

    return [core] + [m for m in (alio.MIGRATIONS, lawgo.MIGRATIONS) if m is not None]
