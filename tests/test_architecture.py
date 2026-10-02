"""overview §2.2 의존 규칙: 위반 import가 하나라도 있으면 실패한다."""
import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "reg"
ALLOW = {
    "reg.platform": ["reg.platform"],
    "reg.core": ["reg.platform", "reg.core"],
    "reg.sources.alio": ["reg.platform", "reg.core", "reg.sources.alio"],
    "reg.sources.lawgo": ["reg.platform", "reg.core", "reg.sources.lawgo"],
    "reg.index": ["reg.platform", "reg.core", "reg.index"],
    "reg.graph": ["reg.platform", "reg.core", "reg.graph"],
    "reg.ocr": ["reg.platform", "reg.core", "reg.ocr"],
    "reg.alerts": ["reg.platform", "reg.core", "reg.graph", "reg.alerts"],
    "reg.qa": ["reg.platform", "reg.core", "reg.index", "reg.qa"],
}


def _module(path: Path) -> str:
    rel = path.relative_to(SRC.parent).with_suffix("")
    return ".".join(p for p in rel.parts if p != "__init__")


def _imports(path: Path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module
        elif isinstance(node, ast.Import):
            yield from (a.name for a in node.names)


def test_dependency_rules():
    bad = []
    for f in SRC.rglob("*.py"):
        mod = _module(f)
        owner = next((k for k in sorted(ALLOW, key=len, reverse=True) if mod == k or mod.startswith(k + ".")), None)
        if owner is None:
            continue  # 앱 계층 (api, cli, wiring, ops)
        for imp in _imports(f):
            if imp.startswith("reg.") and not any(imp == a or imp.startswith(a + ".") for a in ALLOW[owner]):
                bad.append(f"{mod} → {imp}")
    assert bad == []


def test_unregistered_topic_is_an_error(conn, tmp_path):
    import pytest

    from reg.core.ingest import registry
    from reg.core.ingest.process import process_once
    from reg.platform.outbox import write
    from reg.platform.storage.blob import LocalBlobStore

    saved = registry.handlers()
    registry.clear()
    try:
        write(conn, "regulation.source_fetched", {"seq": "1", "source_document_id": 1})
        conn.commit()
        with pytest.raises(RuntimeError, match="처리기"):
            process_once(conn, LocalBlobStore(tmp_path))
    finally:
        for h in saved.values():
            registry.register(h)
