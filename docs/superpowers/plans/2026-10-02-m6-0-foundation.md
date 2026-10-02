# M6-0 기반: 모듈 재배치 · 출처 처리기 계약 · 전용 DB Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 출처별 모듈(ALIO·law.go.kr)과 공통 기반·도메인(core)을 분리하고, nst-nexus와 분리된 전용 DB(`nst_regulation`: `regulation`/`law`/`ops`)로 옮긴다. 병렬 트랙(M6-1~5)이 기댈 계약(처리기 등록부, 마이그레이션 위치, tasks.py 진입점, 0008 스키마)을 만든다.

**Architecture:**
- 동작을 바꾸지 않는 파일 이동을 먼저 한다. 기존 테스트 196개가 그대로 통과해야 한다.
- 이어서 `core.ingest`가 출처를 모르게 등록부로 바꾸고, 의존 규칙을 AST 테스트로 강제한다.
- DB는 부트스트랩이 전용 DB와 스키마 3개를 만든다. 마이그레이션은 위치(core/alio/lawgo)별 이력으로 돈다.

**Tech Stack:** Python 3.13, psycopg3, Alembic, typer, pytest + testcontainers

**Spec:** `docs/superpowers/specs/2026-10-02-batch-pipeline-design.md` (§1A, §3.3, §3A.2, §5.4) · 계약: `docs/superpowers/plans/2026-10-02-m6-overview.md`

## Global Constraints

- 패키지 배치·의존 규칙·계약은 overview §2를 그대로 따른다.
- 기존 outbox 주제 이름(`regulation.source_fetched`, `regulation.law_fetched`, `regulation.version_loaded`)을 유지한다. 실데이터 이벤트 2,200여 건이 이 이름이다.
- 전용 DB 이름 `nst_regulation`, 스키마 `regulation`·`law`·`ops`. 역할은 기존 `reg_migrator`(소유)와 `reg_app`(DML)이다.
- core 마이그레이션 이력(0001~0008)은 이 트랙만 고친다.
- 실서버 이전(Task 6) 전까지 실 DB에 쓰지 않는다.

## Review Focus

1. **이동 후 문자열로 남은 옛 모듈 경로**: monkeypatch 대상 문자열이나 지연 import가 옛 경로를 가리키면 실행할 때만 깨진다. 이동 스크립트가 `.py` 전체에서 점 경로를 치환하고, Task 1 끝에서 `grep -rn "reg\.(collect|structure|search|load|views|extract)\b"`가 0건이어야 한다.
2. **처리기가 등록되지 않은 채 `process_once` 호출**: 이벤트가 소리 없이 쌓이면 안 된다. 등록되지 않은 주제가 대기 중이면 `RuntimeError`를 낸다(Task 2 테스트).
3. **0008의 스키마 이동 후 기본 권한**: `ops`로 옮긴 테이블과 이후 `ops`에 새로 만드는 테이블 모두 `reg_app`이 쓸 수 있어야 한다(Task 4 테스트).
4. **부트스트랩 두 번 실행**: 멱등이어야 한다(Task 3 테스트).
5. **실서버 이전 중 서비스 중단**: 덤프·복원 동안 쓰기가 없어야 한다. 작업자와 API를 멈추고 이전한 뒤 행 수를 대조한다(Task 6).

---

### Task 1: 파일 재배치 (동작 변경 없음)

**Files:**
- Create: `scripts/m6_restructure.py`
- Move: overview §2.1 배치대로 (아래 MOVES)
- Modify: 모든 `src/**/*.py`, `tests/**/*.py`의 import 경로, `alembic.ini`

**Interfaces:**
- Produces: 새 모듈 경로. 이후 모든 Task와 트랙이 이 경로를 쓴다.

- [ ] **Step 1: 이동 스크립트 작성**

```python
# scripts/m6_restructure.py
"""M6-0: 파일을 새 패키지 배치로 옮기고 점 경로(import·문자열)를 모두 바꾼다. 한 번만 실행한다."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
S = ROOT / "src/reg"
MOVES = [  # (옛 파일, 새 파일)
    ("settings.py", "platform/settings.py"), ("outbox.py", "platform/outbox.py"),
    ("db/bootstrap.py", "platform/db/bootstrap.py"), ("db/conn.py", "platform/db/conn.py"),
    ("db/migrate.py", "platform/db/migrate.py"), ("storage/blob.py", "platform/storage/blob.py"),
    ("collect/polite.py", "platform/http.py"), ("collect/runs.py", "platform/runs.py"),
    ("collect/sniff.py", "platform/sniff.py"), ("collect/archive.py", "platform/archive.py"),
    ("views/converter.py", "platform/convert.py"), ("llm.py", "platform/llm.py"),
    ("structure/model.py", "core/model.py"), ("structure/text.py", "core/text.py"),
    ("structure/parse.py", "core/parse.py"), ("structure/effective.py", "core/effective.py"),
    ("extract/__init__.py", "core/extract/__init__.py"), ("extract/hwp.py", "core/extract/hwp.py"),
    ("extract/hwpx.py", "core/extract/hwpx.py"), ("extract/pdf.py", "core/extract/pdf.py"),
    ("views/anchor.py", "core/anchor.py"), ("load/loader.py", "core/ingest/loader.py"),
    ("process.py", "core/ingest/process.py"), ("refs.py", "core/refs.py"), ("quality.py", "core/quality.py"),
    ("collect/alio.py", "sources/alio/client.py"), ("collect/alio_sync.py", "sources/alio/sync.py"),
    ("collect/lawgo.py", "sources/lawgo/client.py"), ("collect/law_sync.py", "sources/lawgo/sync.py"),
    ("structure/law_xml.py", "sources/lawgo/xml.py"),
    ("search/chunks.py", "index/chunks.py"), ("search/indexer.py", "index/indexer.py"),
    ("search/mapping.py", "index/mapping.py"), ("search/os.py", "index/os.py"),
    ("search/service.py", "index/service.py"), ("evaluate.py", "qa/evaluate.py"),
]
DIRS = [("migrations", "core/migrations")]
# 점 경로 치환 (긴 것부터)
PATHS = {
    "reg.collect.alio_sync": "reg.sources.alio.sync", "reg.collect.alio": "reg.sources.alio.client",
    "reg.collect.law_sync": "reg.sources.lawgo.sync", "reg.collect.lawgo": "reg.sources.lawgo.client",
    "reg.collect.polite": "reg.platform.http", "reg.collect.runs": "reg.platform.runs",
    "reg.collect.sniff": "reg.platform.sniff", "reg.collect.archive": "reg.platform.archive",
    "reg.structure.law_xml": "reg.sources.lawgo.xml", "reg.structure.model": "reg.core.model",
    "reg.structure.text": "reg.core.text", "reg.structure.parse": "reg.core.parse",
    "reg.structure.effective": "reg.core.effective", "reg.views.converter": "reg.platform.convert",
    "reg.views.anchor": "reg.core.anchor", "reg.load.loader": "reg.core.ingest.loader",
    "reg.storage.blob": "reg.platform.storage.blob", "reg.db.bootstrap": "reg.platform.db.bootstrap",
    "reg.db.conn": "reg.platform.db.conn", "reg.db.migrate": "reg.platform.db.migrate",
    "reg.extract": "reg.core.extract", "reg.search": "reg.index", "reg.process": "reg.core.ingest.process",
    "reg.refs": "reg.core.refs", "reg.quality": "reg.core.quality", "reg.settings": "reg.platform.settings",
    "reg.outbox": "reg.platform.outbox", "reg.llm": "reg.platform.llm", "reg.evaluate": "reg.qa.evaluate",
}
FROM_REG = {"outbox": "reg.platform", "evaluate": "reg.qa"}  # from reg import outbox / evaluate


def git(*a):
    subprocess.run(["git", "-C", str(ROOT), *a], check=True)


def main():
    for old, new in MOVES:
        (S / new).parent.mkdir(parents=True, exist_ok=True)
        git("mv", str(S / old), str(S / new))
    for old, new in DIRS:
        (S / new).parent.mkdir(parents=True, exist_ok=True)
        git("mv", str(S / old), str(S / new))
    for d in ["platform", "platform/db", "platform/storage", "core", "core/ingest", "sources", "sources/alio",
              "sources/lawgo", "index"]:
        init = S / d / "__init__.py"
        if not init.exists():
            init.write_text("")
    pat = re.compile(r"\b(" + "|".join(re.escape(k) for k in sorted(PATHS, key=len, reverse=True)) + r")\b")
    for f in list((ROOT / "src").rglob("*.py")) + list((ROOT / "tests").rglob("*.py")) + list((ROOT / "scripts").rglob("*.py")):
        if f.name == "m6_restructure.py":
            continue
        t = f.read_text(encoding="utf-8")
        n = pat.sub(lambda m: PATHS[m[1]], t)
        for name, pkg in FROM_REG.items():
            n = re.sub(rf"^(\s*)from reg import {name}\b", rf"\1from {pkg} import {name}", n, flags=re.M)
        if n != t:
            f.write_text(n, encoding="utf-8")
    for leftover in ["collect", "structure", "load", "views", "search", "extract", "storage", "db"]:
        p = S / leftover
        if p.exists():
            for x in p.glob("__init__.py"):
                git("rm", "-q", str(x))
            if p.exists() and not any(p.iterdir()):
                p.rmdir()
    ini = ROOT / "alembic.ini"
    ini.write_text(ini.read_text().replace("src/reg/migrations", "src/reg/core/migrations"))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 실행하고 경로 고정 확인**

옮긴 파일 안의 `Path(__file__)` 기준 경로(`platform/db/migrate.py`의 MIGRATIONS, `cli.py`의 ROOT)는 손으로 고친다.
- `migrate.py`: `MIGRATIONS = Path(__file__).resolve().parents[2] / "core" / "migrations"`
- 다른 `parents[n]` 사용처는 `grep -n "parents\[" -r src`로 찾아 깊이를 맞춘다.

Run: `uv run python scripts/m6_restructure.py && grep -rnE "reg\.(collect|structure|search|load|views|extract)\b|from reg import (outbox|evaluate)" src tests | wc -l`
Expected: `0`

- [ ] **Step 3: 전체 테스트**

Run: `uv run pytest -q`
Expected: 196 passed (이전과 같은 수)

- [ ] **Step 4: 커밋**

```bash
git add -A src tests scripts alembic.ini
git commit -m "refactor: move modules into platform/core/sources/index packages (no behavior change)"
```

---

### Task 2: 출처 처리기 등록부 · 출처 모듈 · 모듈별 CLI · 아키텍처 테스트

**Files:**
- Create: `src/reg/core/ingest/contract.py`, `src/reg/core/ingest/registry.py`, `src/reg/sources/alio/handler.py`, `src/reg/sources/lawgo/handler.py`, `src/reg/sources/alio/__init__.py`, `src/reg/sources/lawgo/__init__.py`, `src/reg/wiring.py`, `src/reg/sources/alio/cli.py`, `src/reg/sources/lawgo/cli.py`, `src/reg/core/cli.py`, `src/reg/index/cli.py`, `src/reg/graph/cli.py`, `src/reg/alerts/cli.py`, `tests/test_architecture.py`
- Modify: `src/reg/core/ingest/process.py`(처리기 직접 import 제거), `src/reg/cli.py`(하위 CLI를 wiring에서 붙임), `tests/conftest.py`(세션 시작 시 `register_sources()`)

**Interfaces:**
- Produces: overview §2.3 (`PreparedVersion`, `SourceHandler`, `register`, `handlers`, `clear`), `reg.wiring.register_sources()`, `reg.wiring.SUBCOMMANDS: list[tuple[str, typer.Typer]]`
- CLI 명령 이름은 그대로 둔다: `reg collect alio|law`, `reg process`, `reg index …`, `reg graph …`, `reg alerts …`, `reg owners …`, `reg eval …`, `reg db …`, `reg bucket …`, `reg api`. 새 별칭 `reg alio collect`, `reg law collect`를 추가한다.

- [ ] **Step 1: 실패하는 테스트**

```python
# tests/test_architecture.py
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
```

Run: `uv run pytest tests/test_architecture.py -q`
Expected: FAIL. `core.ingest.process → reg.sources.lawgo.xml` 위반, `registry` 없음.

- [ ] **Step 2: 계약과 등록부**

```python
# src/reg/core/ingest/contract.py
"""출처 모듈 ↔ core 계약 (overview §2.3). 출처는 '적재할 판본 하나'를 만들어 넘기고, 적재는 core가 한다."""
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from reg.core.effective import Effective
from reg.core.model import ParsedDoc


@dataclass
class PreparedVersion:
    work_id: str
    work_kind: str
    title: str
    institution_id: int | None
    source_document_id: int
    doc: ParsedDoc
    effective: Effective
    external_ids: dict = field(default_factory=dict)
    posted_on: date | None = None


@dataclass
class SourceHandler:
    topic: str
    group_field: str
    prepare: Callable[..., PreparedVersion | None]  # (conn, blob, payload, today, converter)
```

```python
# src/reg/core/ingest/registry.py
"""출처 처리기 등록부. core는 출처 모듈을 import하지 않고, 앱 계층(reg.wiring)이 여기에 등록한다."""
from reg.core.ingest.contract import SourceHandler

_HANDLERS: dict[str, SourceHandler] = {}


def register(h: SourceHandler) -> None:
    _HANDLERS[h.topic] = h


def handlers() -> dict[str, SourceHandler]:
    return dict(_HANDLERS)


def clear() -> None:
    _HANDLERS.clear()
```

- [ ] **Step 3: 처리 함수를 출처 모듈로 옮기고 core가 적재**

`core/ingest/process.py`에서 `prepare_source_fetched`, `prepare_law_fetched`, `_view`, `HANDLERS`, `GROUP_FIELD`를 뺀다.
- `_view`(보기용 PDF)는 ALIO 파일 전용이므로 `sources/alio/handler.py`로 옮긴다.
- 처리기는 `PreparedVersion`을 돌려주고, core가 `upsert_work` + `add_version`을 한다.

```python
# src/reg/sources/alio/handler.py
"""ALIO 내부규정 파일 하나 → PreparedVersion (추출·파싱·시행일·보기용 PDF). 적재는 core가 한다."""
import json
from datetime import date

from reg.core.anchor import locate
from reg.core.effective import resolve
from reg.core.extract import extract
from reg.core.extract.pdf import extract_pdf
from reg.core.ingest.contract import PreparedVersion, SourceHandler
from reg.core.ingest.loader import work_key_for_regulation
from reg.core.parse import parse_blocks
from reg.platform.convert import ConversionError, Converter
from reg.platform.storage.blob import BlobStore

HWP_MIMES = {"application/x-hwp": "hwp", "application/hwp+zip": "hwpx"}
```

그 아래에 Task 1 이후의 `_view` 본문과 `prepare_source_fetched` 본문을 그대로 옮기되 두 군데를 바꾼다.
- 시그니처를 `prepare(conn, blob, payload, today, converter=None) -> PreparedVersion | None`으로 한다.
- 마지막 세 줄(`upsert_work` / `add_version` / `return wid, vid, doc, eff`)을 아래로 바꾼다.

```python
    wid = work_key_for_regulation(conn, rule["inst_code"], rule["institution_id"], rule["title"], rule["seq"])
    return PreparedVersion(wid, "INTERNAL_REG", rule["title"], rule["institution_id"], sd["id"], doc, eff,
                           {"alio_seq": rule["seq"]}, rule["posted_on"])


HANDLER = SourceHandler("regulation.source_fetched", "seq", prepare)
```

```python
# src/reg/sources/lawgo/handler.py
"""법령 XML 판본 하나 → PreparedVersion."""
from datetime import date

from reg.core.effective import resolve
from reg.core.ingest.contract import PreparedVersion, SourceHandler
from reg.sources.lawgo.xml import parse_law_xml


def prepare(conn, blob, payload: dict, today: date, converter=None) -> PreparedVersion:
    sd = conn.execute("SELECT * FROM regulation.source_document WHERE id = %s",
                      (payload["source_document_id"],)).fetchone()
    doc = parse_law_xml(blob.get(sd["blob_key"]))
    return PreparedVersion(f"kr/law/{payload['law_id']}", doc.meta.get("kind") or "LAW", doc.title, None, sd["id"],
                           doc, resolve(doc), {"law_id": payload["law_id"], "mst": payload["mst"]})


HANDLER = SourceHandler("regulation.law_fetched", "law_id", prepare)
```

```python
# src/reg/sources/alio/__init__.py
from reg.sources.alio.handler import HANDLER

HANDLERS = [HANDLER]
```

```python
# src/reg/sources/lawgo/__init__.py
from reg.sources.lawgo.handler import HANDLER

HANDLERS = [HANDLER]
```

`core/ingest/process.py`의 묶음 처리는 등록부를 쓴다.

```python
from reg.core.ingest import registry
from reg.core.ingest.loader import add_version, rebuild_work, upsert_work


def _topics() -> list[str]:
    return list(registry.handlers())


def _check_unhandled(conn) -> None:
    """등록되지 않은 주제의 대기 이벤트가 있으면 조용히 쌓이지 않게 멈춘다."""
    known = _topics()
    row = conn.execute("SELECT topic FROM regulation.outbox WHERE processed_at IS NULL AND attempts < %s"
                       " AND topic LIKE 'regulation.%%fetched' AND NOT (topic = ANY(%s)) LIMIT 1",
                       (MAX_ATTEMPTS, known)).fetchone()
    if row:
        raise RuntimeError(f"처리기가 등록되지 않은 주제: {row['topic']} (reg.wiring.register_sources() 필요)")


def _load(conn, pv) -> tuple:
    upsert_work(conn, pv.work_id, pv.work_kind, pv.title, pv.institution_id, pv.external_ids)
    vid = add_version(conn, pv.work_id, pv.source_document_id, pv.doc, pv.effective, posted_on=pv.posted_on)
    return pv.work_id, vid, pv.doc, pv.effective
```

`process_once`에서 바꿀 곳은 다음과 같다.
- 시작에서 `_check_unhandled(conn)`을 부른다.
- `TOPICS`를 `_topics()`로 바꾼다.
- `GROUP_FIELD[...]`를 `registry.handlers()[topic].group_field`로 바꾼다.
- 처리기 호출을 `pv = handlers[ev["topic"]].prepare(conn, blob, ev["payload"], today, converter)`로 바꾸고, `None`이 아니면 `_load(conn, pv)`의 결과를 `done`에 넣는다.

`rebuild_all`의 `TOPICS`도 `_topics()`로 바꾼다.

- [ ] **Step 4: wiring과 모듈별 CLI**

```python
# src/reg/wiring.py
"""앱 계층 조립: 출처 처리기 등록, 하위 CLI 목록, 마이그레이션 위치 (Task 4에서 추가)."""
from reg.core.ingest import registry


def register_sources() -> None:
    from reg.sources import alio, lawgo

    for h in alio.HANDLERS + lawgo.HANDLERS:
        registry.register(h)


def subcommands() -> list:
    from reg.alerts.cli import alerts, owners
    from reg.core.cli import process_app
    from reg.graph.cli import graph
    from reg.index.cli import index
    from reg.sources.alio.cli import alio
    from reg.sources.lawgo.cli import law

    return [("alio", alio), ("law", law), ("index", index), ("graph", graph), ("alerts", alerts),
            ("owners", owners), ("process", process_app)]
```

`src/reg/cli.py`의 명령 본문을 모듈별 `cli.py`로 옮긴다.
- 각 모듈 `cli.py`는 `typer.Typer` 하나를 내놓는다.
- `reg/cli.py`가 `wiring.subcommands()`를 `app.add_typer`로 붙인다.
- `reg collect alio|law`는 기존 이름을 유지하기 위해 `reg/cli.py`에 남긴 얇은 별칭으로 둔다. 별칭은 `sources.alio.cli`와 `sources.lawgo.cli`의 같은 함수를 부른다.
- `reg process`는 기존처럼 최상위 명령이어야 한다. 그래서 `core/cli.py`는 `process_cmd` 함수를 내놓고, `reg/cli.py`가 `app.command("process")(process_cmd)`로 붙인다(`process_app` 대신). wiring 목록에서는 `("process", …)`를 빼고 `reg/cli.py`가 직접 붙인다.
- 각 명령 첫 줄에서 `register_sources()`를 한 번 부른다.

`tests/conftest.py`에 다음을 추가한다.

```python
@pytest.fixture(scope="session", autouse=True)
def _sources():
    from reg.wiring import register_sources

    register_sources()
```

- [ ] **Step 5: 통과 확인**

Run: `uv run pytest -q`
Expected: 198 passed (기존 196 + 새 2)

Run: `uv run reg --help | grep -E "alio|law|process|index|graph|alerts|collect"`
Expected: 명령이 모두 보인다.

- [ ] **Step 6: 커밋**

```bash
git add -A src tests
git commit -m "refactor: source handler registry, per-module CLIs, dependency-rule test"
```

---

### Task 3: 전용 DB 부트스트랩

**Files:**
- Modify: `src/reg/platform/db/bootstrap.py`, `src/reg/platform/settings.py`(기본 URL), `tests/conftest.py`, `.env.example`, `src/reg/platform/cli.py` 또는 `reg/cli.py`의 `db bootstrap`
- Test: `tests/test_bootstrap.py`

**Interfaces:**
- Produces: `bootstrap(superuser_dsn, db_name="nst_regulation", migrator_password, app_password)`. DB(소유자 reg_migrator)와 스키마 `regulation`·`law`·`ops`를 만든다. `reg_app`은 USAGE와 DML 기본 권한을 갖는다.

- [ ] **Step 1: 실패하는 테스트**

```python
# tests/test_bootstrap.py
import psycopg

from reg.platform.db.bootstrap import bootstrap
from tests.conftest import _dsn


def test_bootstrap_creates_dedicated_db_and_schemas_idempotently(pg):
    su = _dsn(pg, "su", "su", pg.dbname)
    bootstrap(su, "nst_regulation", "mig", "app")
    bootstrap(su, "nst_regulation", "mig", "app")  # 두 번째도 오류 없이
    with psycopg.connect(_dsn(pg, "reg_migrator", "mig", "nst_regulation")) as c:
        got = {r[0] for r in c.execute("SELECT nspname FROM pg_namespace").fetchall()}
        assert {"regulation", "law", "ops"} <= got
        c.execute("CREATE TABLE ops.t_probe (x int)")
        c.commit()
    with psycopg.connect(_dsn(pg, "reg_app", "app", "nst_regulation")) as c:
        c.execute("INSERT INTO ops.t_probe VALUES (1)")  # 기본 권한으로 reg_app이 쓴다
        c.commit()
```

`_dsn`의 시그니처를 `_dsn(c, user, pw, db)`로 바꾼다. 기존 호출도 고친다.

Run: `uv run pytest tests/test_bootstrap.py -q`
Expected: FAIL (`nst_regulation` 데이터베이스 없음)

- [ ] **Step 2: 구현**

```python
# src/reg/platform/db/bootstrap.py
"""공유 Postgres 서버에 이 프로젝트 전용 DB(nst_regulation)·역할·스키마를 만든다. 슈퍼유저 DSN으로 실행 (멱등)."""
from urllib.parse import urlparse, urlunparse

import psycopg
from psycopg import sql

SCHEMAS = ("regulation", "law", "ops")


def _ensure_role(cur, name: str, password: str) -> None:
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (name,))
    verb = "ALTER" if cur.fetchone() else "CREATE"
    cur.execute(sql.SQL(verb + " ROLE {} LOGIN PASSWORD {}").format(sql.Identifier(name), sql.Literal(password)))


def _with_db(dsn: str, db: str) -> str:
    u = urlparse(dsn)
    return urlunparse(u._replace(path="/" + db))


def bootstrap(superuser_dsn: str, db_name: str, migrator_password: str, app_password: str) -> None:
    db = sql.Identifier(db_name)
    with psycopg.connect(superuser_dsn, autocommit=True) as c, c.cursor() as cur:
        _ensure_role(cur, "reg_migrator", migrator_password)
        _ensure_role(cur, "reg_app", app_password)
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
        if not cur.fetchone():
            cur.execute(sql.SQL("CREATE DATABASE {} OWNER reg_migrator").format(db))
        cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO reg_migrator, reg_app").format(db))
    with psycopg.connect(_with_db(superuser_dsn, db_name), autocommit=True) as c, c.cursor() as cur:
        for s in SCHEMAS:
            name = sql.Identifier(s)
            cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {} AUTHORIZATION reg_migrator").format(name))
            cur.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO reg_app").format(name))
            cur.execute(sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE reg_migrator IN SCHEMA {}"
                                " GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON TABLES TO reg_app").format(name))
            cur.execute(sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE reg_migrator IN SCHEMA {}"
                                " GRANT USAGE, SELECT ON SEQUENCES TO reg_app").format(name))
```

conftest의 `migrated`는 다음처럼 바꾼다.

```python
@pytest.fixture(scope="session")
def migrated(pg):
    from reg.wiring import migration_locations  # Task 4 전에는 upgrade(mig)

    su = _dsn(pg, "su", "su", pg.dbname)
    bootstrap(su, "nst_regulation", "mig", "app")
    mig, app = _dsn(pg, "reg_migrator", "mig", "nst_regulation"), _dsn(pg, "reg_app", "app", "nst_regulation")
    upgrade(mig, migration_locations())
    return app, mig
```

Task 3 시점에는 `upgrade(mig)`로 둔다. Task 4에서 위처럼 바꾼다.

settings 기본값은 `…/nst_regulation`으로 바꾼다. `.env.example`도 같은 값으로 바꾼다. `db bootstrap` 명령은 `db_name` 기본값을 `nst_regulation`으로 넘긴다.

- [ ] **Step 3: 통과 확인**

Run: `uv run pytest -q`
Expected: 전체 통과 (+1)

- [ ] **Step 4: 커밋**

```bash
git add -A src tests .env.example
git commit -m "feat(db): dedicated nst_regulation database with regulation/law/ops schemas"
```

---

### Task 4: 위치별 마이그레이션 · 0008 · alio a001

**Files:**
- Modify: `src/reg/platform/db/migrate.py`, `src/reg/core/migrations/env.py`, `src/reg/wiring.py`, `src/reg/sources/alio/__init__.py`, `tests/conftest.py`
- Create: `src/reg/core/migrations/versions/0008_ops_and_m6.py`, `src/reg/sources/alio/migrations/{env.py,script.py.mako,versions/a001_missing_since.py}`, `scripts/m6_ops_rename.py`
- Test: `tests/test_migrations_0008.py`

**Interfaces:**
- Produces: overview §2.4 `MigrationLocation`, `upgrade(dsn, locations)`, `reg.wiring.migration_locations()`; overview §2.5 스키마; `regulation.alio_rule.missing_since`
- 코드의 `regulation.<ops 테이블>`은 모두 `ops.<테이블>`이 된다.

- [ ] **Step 1: 실패하는 테스트**

```python
# tests/test_migrations_0008.py
def test_ops_schema_and_m6_columns(conn):
    tables = {(r["table_schema"], r["table_name"]) for r in conn.execute(
        "SELECT table_schema, table_name FROM information_schema.tables"
        " WHERE table_schema IN ('regulation', 'ops')").fetchall()}
    for t in ("outbox", "fetch_run", "request_log", "release", "release_item", "qa_log", "change_impact",
              "owner_assignment", "notification", "email_delivery", "pipeline_run", "embedding_cache"):
        assert ("ops", t) in tables and ("regulation", t) not in tables
    cols = {(r["table_name"], r["column_name"]) for r in conn.execute(
        "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'regulation'").fetchall()}
    assert {("work", "status"), ("work", "abolished_on"), ("work_version", "parser_version"),
            ("source_document", "ocr_status"), ("source_document", "ocr_blob_key"), ("source_document", "ocr_engine"),
            ("alio_rule", "missing_since")} <= cols
    assert conn.execute("SELECT count(*) AS n FROM regulation.alembic_version_alio").fetchone()["n"] == 1
    conn.execute("INSERT INTO ops.pipeline_run (dag_id, task_id) VALUES ('d', 't')")  # reg_app이 쓴다
```

Run: `uv run pytest tests/test_migrations_0008.py -q`
Expected: FAIL

- [ ] **Step 2: 위치별 실행기**

```python
# src/reg/platform/db/migrate.py
"""모듈별 Alembic 이력(위치)을 순서대로 head까지 올린다 (overview §2.4)."""
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config


@dataclass(frozen=True)
class MigrationLocation:
    name: str
    path: Path
    schema: str
    version_table: str


def alembic_config(migrator_dsn: str, loc: MigrationLocation) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(loc.path))
    cfg.set_main_option("sqlalchemy.url", migrator_dsn.replace("postgresql://", "postgresql+psycopg://", 1))
    cfg.set_main_option("version_table_schema", loc.schema)
    cfg.set_main_option("version_table", loc.version_table)
    return cfg


def upgrade(migrator_dsn: str, locations: list[MigrationLocation], revision: str = "head") -> None:
    for loc in locations:
        command.upgrade(alembic_config(migrator_dsn, loc), revision)
```

core와 alio의 `env.py`는 같은 내용이다.

```python
from alembic import context
from sqlalchemy import create_engine

cfg = context.config
engine = create_engine(cfg.get_main_option("sqlalchemy.url"))
with engine.connect() as connection:
    context.configure(connection=connection, version_table_schema=cfg.get_main_option("version_table_schema"),
                      version_table=cfg.get_main_option("version_table"))
    with context.begin_transaction():
        context.run_migrations()
```

```python
# src/reg/core/migrations/__init__.py 대신 core에 위치를 정의 (src/reg/core/ingest/migrations_location.py)
from pathlib import Path

from reg.platform.db.migrate import MigrationLocation

MIGRATIONS = MigrationLocation("core", Path(__file__).resolve().parents[1] / "migrations", "regulation",
                               "alembic_version")
```

`sources/alio/__init__.py`에 다음을 추가한다.

```python
from pathlib import Path

from reg.platform.db.migrate import MigrationLocation

MIGRATIONS = MigrationLocation("alio", Path(__file__).resolve().parent / "migrations", "regulation",
                               "alembic_version_alio")
```

`sources/lawgo/__init__.py`에는 `MIGRATIONS = None`을 둔다. M6-1이 채운다.

```python
# reg/wiring.py에 추가
def migration_locations() -> list:
    from reg.core.ingest.migrations_location import MIGRATIONS as core
    from reg.sources import alio, lawgo

    return [core] + [m for m in (alio.MIGRATIONS, lawgo.MIGRATIONS) if m is not None]
```

`reg db upgrade`와 conftest는 `upgrade(mig, migration_locations())`를 쓴다. 기존 `script_location`의 `alembic.ini`는 지운다. 위치마다 다르므로 코드에서만 설정한다.

- [ ] **Step 3: 0008과 a001**

```python
# src/reg/core/migrations/versions/0008_ops_and_m6.py
"""운영 테이블을 ops 스키마로, M6 트랙이 쓸 컬럼·테이블 (overview §2.5)."""
from alembic import op

revision = "0008"
down_revision = "0007"
OPS = ["outbox", "fetch_run", "request_log", "release", "release_item", "qa_log", "change_impact",
       "owner_assignment", "notification", "email_delivery"]


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS ops")
    for t in OPS:
        op.execute(f"ALTER TABLE regulation.{t} SET SCHEMA ops")
    op.execute("""
ALTER TABLE regulation.work ADD COLUMN status text NOT NULL DEFAULT 'ACTIVE'
  CHECK (status IN ('ACTIVE', 'ABOLISHED_CANDIDATE', 'ABOLISHED')),
  ADD COLUMN abolished_on date;
ALTER TABLE regulation.work_version ADD COLUMN parser_version text;
ALTER TABLE regulation.source_document ADD COLUMN ocr_status text
  CHECK (ocr_status IN ('pending', 'ready', 'failed', 'not_needed')),
  ADD COLUMN ocr_blob_key text, ADD COLUMN ocr_engine text;
CREATE TABLE ops.pipeline_run (
  id bigserial PRIMARY KEY, dag_id text, run_id text, task_id text NOT NULL,
  started_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz,
  status text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'success', 'failed')),
  stats jsonb NOT NULL DEFAULT '{}', error text);
CREATE INDEX ON ops.pipeline_run (started_at);
CREATE TABLE ops.embedding_cache (
  text_hash text NOT NULL, model text NOT NULL, vector real[] NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (text_hash, model));""")


def downgrade() -> None:
    op.execute("DROP TABLE ops.embedding_cache; DROP TABLE ops.pipeline_run;"
               " ALTER TABLE regulation.source_document DROP COLUMN ocr_engine, DROP COLUMN ocr_blob_key,"
               " DROP COLUMN ocr_status; ALTER TABLE regulation.work_version DROP COLUMN parser_version;"
               " ALTER TABLE regulation.work DROP COLUMN abolished_on, DROP COLUMN status;")
    for t in OPS:
        op.execute(f"ALTER TABLE ops.{t} SET SCHEMA regulation")
```

```python
# src/reg/sources/alio/migrations/versions/a001_missing_since.py
"""ALIO 목록에서 사라진 날 (폐지 감지, spec §3.3). alio 모듈 이력의 첫 리비전."""
from alembic import op

revision = "a001"
down_revision = None


def upgrade() -> None:
    op.execute("ALTER TABLE regulation.alio_rule ADD COLUMN missing_since date")


def downgrade() -> None:
    op.execute("ALTER TABLE regulation.alio_rule DROP COLUMN missing_since")
```

`script.py.mako`는 core의 것을 복사한다.

- [ ] **Step 4: 코드의 테이블 이름 치환**

```python
# scripts/m6_ops_rename.py
"""코드·테스트의 regulation.<운영 테이블>을 ops.<테이블>로 바꾼다 (0008과 짝). 한 번만 실행한다."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPS = ["release_item", "release", "outbox", "fetch_run", "request_log", "qa_log", "change_impact",
       "owner_assignment", "notification", "email_delivery"]
pat = re.compile(r"\bregulation\.(" + "|".join(OPS) + r")\b")
for f in list((ROOT / "src").rglob("*.py")) + list((ROOT / "tests").rglob("*.py")):
    if "migrations/versions" in str(f):
        continue  # 지난 리비전은 그때의 이름 그대로
    t = f.read_text(encoding="utf-8")
    n = pat.sub(r"ops.\1", t)
    if n != t:
        f.write_text(n, encoding="utf-8")
```

conftest의 TRUNCATE 목록은 스크립트가 함께 바꾼다. `ops.pipeline_run`과 `ops.embedding_cache`는 직접 추가한다.

Run: `uv run python scripts/m6_ops_rename.py && uv run pytest -q`
Expected: 전체 통과 (+1)

- [ ] **Step 5: 커밋**

```bash
git add -A src tests scripts alembic.ini
git commit -m "feat(db): per-module migration histories, ops schema (0008), alio a001"
```

---

### Task 5: 실행 이력과 tasks.py 진입점 · 파서 버전

**Files:**
- Modify: `src/reg/platform/runs.py`(`task_run` 추가), `src/reg/core/ingest/loader.py`(`add_version`이 `parser_version` 기록), `src/reg/core/parse.py`(`PARSER_VERSION`)
- Create: `src/reg/sources/alio/tasks.py`, `src/reg/core/ingest/tasks.py`, `src/reg/graph/tasks.py`, `src/reg/alerts/tasks.py`, `src/reg/index/tasks.py`, `src/reg/ops/__init__.py`
- Test: `tests/test_tasks.py`

**Interfaces:**
- Produces: overview §2.6 중 M6-0 몫.
  - `alio.tasks.active_institutions`, `alio.tasks.collect_institution`
  - `core.ingest.tasks.process_all`, `core.ingest.tasks.quality_summary`
  - `graph.tasks.sync`
  - `alerts.tasks.scan`, `alerts.tasks.notify`
  - `index.tasks.build`
- Produces: `reg.platform.runs.task_run(task_id: str, conn) -> ContextManager[dict]`.
  - 블록 안에서 채운 dict를 `ops.pipeline_run.stats`에 넣는다.
  - 예외가 나면 `failed`와 `error`를 기록하고 예외를 다시 던진다.
  - Airflow 환경변수 `AIRFLOW_CTX_DAG_ID`와 `AIRFLOW_CTX_DAG_RUN_ID`가 있으면 그 값을 기록한다.
- Produces: `PARSER_VERSION = "2026.10.2"`. 판본마다 `work_version.parser_version`에 기록한다.

- [ ] **Step 1: 실패하는 테스트**

```python
# tests/test_tasks.py
import pytest


def test_task_run_records_success_and_failure(conn, monkeypatch):
    from reg.platform.runs import task_run

    monkeypatch.setenv("AIRFLOW_CTX_DAG_ID", "reg_alio_daily")
    with task_run("probe", conn) as st:
        st["n"] = 3
    with pytest.raises(ValueError), task_run("boom", conn):
        raise ValueError("x")
    rows = {r["task_id"]: r for r in conn.execute("SELECT * FROM ops.pipeline_run").fetchall()}
    assert rows["probe"]["status"] == "success" and rows["probe"]["stats"] == {"n": 3}
    assert rows["probe"]["dag_id"] == "reg_alio_daily"
    assert rows["boom"]["status"] == "failed" and "ValueError" in rows["boom"]["error"]


def test_parser_version_recorded(loaded):
    from reg.core.parse import PARSER_VERSION

    v = loaded.execute("SELECT parser_version FROM regulation.work_version LIMIT 1").fetchone()
    assert v["parser_version"] == PARSER_VERSION


def test_tasks_entrypoints_exist():
    from reg.alerts import tasks as at
    from reg.core.ingest import tasks as ct
    from reg.graph import tasks as gt
    from reg.index import tasks as it
    from reg.sources.alio import tasks as alt

    for f in (alt.active_institutions, alt.collect_institution, ct.process_all, ct.quality_summary, gt.sync,
              at.scan, at.notify, it.build):
        assert callable(f)
```

Run: `uv run pytest tests/test_tasks.py -q`
Expected: FAIL

- [ ] **Step 2: task_run**

```python
# src/reg/platform/runs.py에 추가
import json
import os
from contextlib import contextmanager


@contextmanager
def task_run(task_id: str, conn):
    """배치 태스크 한 번의 실행을 ops.pipeline_run에 남긴다 (Airflow·CLI 공통)."""
    rid = conn.execute("INSERT INTO ops.pipeline_run (dag_id, run_id, task_id) VALUES (%s, %s, %s) RETURNING id",
                       (os.environ.get("AIRFLOW_CTX_DAG_ID"), os.environ.get("AIRFLOW_CTX_DAG_RUN_ID"),
                        task_id)).fetchone()["id"]
    conn.commit()
    stats: dict = {}
    try:
        yield stats
    except Exception as e:
        conn.rollback()
        conn.execute("UPDATE ops.pipeline_run SET status = 'failed', finished_at = now(), stats = %s, error = %s"
                     " WHERE id = %s", (json.dumps(stats, default=str), f"{type(e).__name__}: {e}"[:2000], rid))
        conn.commit()
        raise
    conn.execute("UPDATE ops.pipeline_run SET status = 'success', finished_at = now(), stats = %s WHERE id = %s",
                 (json.dumps(stats, default=str), rid))
    conn.commit()
```

- [ ] **Step 3: tasks.py 진입점**

모든 진입점은 같은 모양이다: 설정을 읽고, 연결하고, `task_run`으로 감싸고, 기존 함수를 부른다. 공통 도우미는 `reg/platform/runs.py`에 둔다.

```python
def open_conn():
    from reg.platform.db.conn import connect
    from reg.platform.settings import get_settings

    return connect(get_settings().database_url)
```

```python
# src/reg/sources/alio/tasks.py
"""Airflow·CLI 진입점 (overview §2.6). 결과는 JSON으로 직렬화할 수 있는 dict."""
from reg.platform.runs import open_conn, task_run


def active_institutions() -> list[str]:
    from reg.sources.alio.sync import load_institutions
    from reg.sources.alio.config import INSTITUTIONS_YAML

    with open_conn() as conn:
        return [i["code"] for i in load_institutions(conn, INSTITUTIONS_YAML)]


def collect_institution(code: str) -> dict:
    from reg.platform.http import PoliteClient
    from reg.platform.runs import open_log_conn
    from reg.platform.settings import get_settings
    from reg.platform.storage.blob import blob_store
    from reg.sources.alio.client import AlioClient
    from reg.sources.alio.sync import load_institutions, sync_institution
    from reg.sources.alio.config import INSTITUTIONS_YAML

    s = get_settings()
    with open_conn() as conn, task_run(f"alio.collect:{code}", conn) as st:
        inst = next(i for i in load_institutions(conn, INSTITUTIONS_YAML) if i["code"] == code)
        with open_log_conn() as log:
            http = PoliteClient("alio", s.alio_min_interval, log=log)
            st.update(sync_institution(conn, AlioClient(http), blob_store(s), inst))
        st["institution"] = code
        return dict(st)
```

- `sources/alio/config.py`: `INSTITUTIONS_YAML = ROOT / "config/sources/alio.yaml"`(기존 `config/institutions.yaml`을 `git mv`)
- `blob_store(s)`: 지금 `cli.py`의 `_blob()` 본문을 `platform/storage/blob.py`로 옮긴 함수
- `open_log_conn()`: 지금 `cli._run`의 로그 연결 생성 부분을 옮긴 함수. 기존 `_run`의 `fetch_run` 기록은 `sync`가 하던 그대로 둔다.

나머지 진입점도 지금 `cli.py`에 있는 본문을 그대로 감싼다.

- `core.ingest.tasks.process_all()`
  - `register_sources()`가 이미 되어 있다고 가정하지 않는다. 앱 계층 함수가 아니므로 등록은 호출자(DAG·CLI)의 몫이다.
  - DAG 쪽에서는 `reg.wiring.register_sources()`를 먼저 부르도록 M6-3에 계약으로 남긴다.
  - 본문: `process_once(conn, blob, converter=…)`를 대기 이벤트가 없을 때까지 반복하고, 합계를 돌려준다.
- `core.ingest.tasks.quality_summary()`
  - 반환: `{kind: count}` (열린 review_task 종류별)와 그날 새로 생긴 수
- `graph.tasks.sync()`
  - `graph_lock` 안에서 `sync_graph`를 돈 뒤 `scan_once`를 반복한다(지금 `reg alerts scan`의 본문).
- `alerts.tasks.scan()`: `--no-sync` 스캔
- `alerts.tasks.notify()`: 지금 `reg alerts notify` 본문
- `index.tasks.build()`: 지금 `reg index build` 본문 (게시 포함; M6-4가 build·gate·publish로 나눈다)

- [ ] **Step 4: 파서 버전**

`core/parse.py`에 `PARSER_VERSION = "2026.10.2"`를 추가한다. `loader.add_version`의 INSERT에 `parser_version` 컬럼과 값 `PARSER_VERSION`을 추가한다(`from reg.core.parse import PARSER_VERSION`).

- [ ] **Step 5: 통과 확인 · 커밋**

Run: `uv run pytest -q`
Expected: 전체 통과 (+3)

```bash
git add -A src tests config
git commit -m "feat: task_run pipeline history, tasks.py entrypoints, parser version"
```

---

### Task 6: 실서버 전용 DB 이전 (메인 세션)

**Files:** 없음 (운영 작업). 결과는 ledger에 기록한다.

- [ ] **Step 1: 쓰기 중지**
  - `scripts/run-dev.sh`가 띄운 API와 웹을 멈춘다(PID 파일 `.run/`).
  - 처리 작업자가 돌고 있지 않은지 `pgrep -af "reg process"`로 확인한다.
- [ ] **Step 2: 부트스트랩**
  - `REG_SUPERUSER_URL`의 DB 경로를 `postgres`로 바꾼 DSN으로 `uv run reg db bootstrap`을 실행한다.
  - 슈퍼유저 비밀번호는 `.env`의 `REG_SUPERUSER_URL`에 있다.
- [ ] **Step 3: 데이터 이전**

```bash
docker exec nais-postgres-1 sh -c 'pg_dump -U nais -d nais -n regulation --no-privileges | psql -U nais -d nst_regulation -v ON_ERROR_STOP=1'
```

  - 이 단계에서 `regulation` 스키마는 이미 있다. 덤프의 `CREATE SCHEMA`가 충돌하면 덤프에서 그 줄을 빼고 다시 실행한다.
  - 소유자는 덤프 그대로 `reg_migrator`다.
  - `--no-privileges`를 썼으므로 이전한 테이블에 `reg_app` 권한이 없다. 그래서 다음을 다시 준다.

```sql
GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA regulation TO reg_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA regulation TO reg_app;
```

- [ ] **Step 4: 접속 주소 전환과 마이그레이션**
  - `.env`의 `REG_DATABASE_URL`과 `REG_MIGRATOR_URL`의 DB를 `nst_regulation`으로 바꾼다.
  - `uv run reg db upgrade`를 실행한다. 0008과 a001이 적용된다.
- [ ] **Step 5: 대조**
  - 테이블별 행 수를 옛 DB(`nais.regulation.*`)와 새 DB(`nst_regulation.regulation.*` + `ops.*`)에서 비교한다. 모두 같아야 한다.
  - `reg index status`, `reg alerts --help`, `bash scripts/run-dev.sh`를 실행한 뒤 다음을 확인한다.
    - 웹 `/regulations`, `/qa`(질문 1개), `/alerts`가 200
    - 질의응답 답변이 정상
- [ ] **Step 6: 옛 스키마**
  - `nais.regulation`은 **지우지 않는다.** 삭제는 사용자 확인 후에 한다.
  - ledger에 "옛 스키마 보존, 사용자 확인 대기"를 기록한다.
