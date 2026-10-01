# M1 기반·수집기 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 대상 기관의 ALIO 내부규정 파일(개정 이력 전체)과 핵심 법령의 law.go.kr 본문을 매일 정중하게 수집해서 원본을 S3에 보관한다. 수집 메타데이터는 `regulation` 스키마에 기록하고, 새 원본이 들어올 때마다 outbox 이벤트를 남긴다.

**Architecture:** 독립 Python 패키지 `reg`.

- 수집 대상은 설정 파일(YAML)에 둔다.
- HTTP는 출처별 `PoliteClient` 하나로 직렬화한다.
- 원본은 내용 해시(SHA-256)를 키로 `BlobStore`에 저장한다.
- 메타데이터는 psycopg3로 공유 Postgres의 `regulation` 스키마에 쓴다. 스키마는 Alembic이 관리하고, 역할과 스키마 생성은 별도 bootstrap 함수가 슈퍼유저로 수행한다.
- 실행은 `reg` CLI(typer)로 한다. 스케줄 워커는 outbox 소비자가 생기는 M2 이후에 둔다.

**Tech Stack:** Python 3.13, uv, httpx, psycopg 3, Alembic(+SQLAlchemy), pydantic-settings, boto3, PyYAML, typer. 테스트는 pytest, respx, testcontainers(postgres:16).

**Spec:** `docs/superpowers/specs/2026-10-01-regulation-platform-design.md` (4.1, 5.3, 6.1, 7절)

## Global Constraints

- **Python:** `requires-python = ">=3.13"`. 패키지 경로는 `src/reg/`, 실행 명령은 `uv run`.
- **DB:**
  - 모든 테이블은 `regulation` 스키마에 둔다.
  - DDL은 `reg_migrator`, DML은 `reg_app` 역할로 수행한다.
  - 다른 스키마는 읽지도 쓰지도 않는다.
  - 마이그레이션 안에서 `CREATE EXTENSION`을 하지 않는다.
- **공유 인프라 엔드포인트:**
  - PostgreSQL `127.0.0.1:21055`, DB `nais`
  - SeaweedFS S3 `http://127.0.0.1:21053`, 버킷 `regulation`
  - 비밀값은 `.env`(gitignore)에서 읽고, 저장소에는 `.env.example`만 둔다.
- **정중한 수집:**
  - 출처별 요청은 직렬로 보낸다.
  - 최소 간격은 ALIO 1.5초, law.go.kr 1.0초다. 응답이 끝난 시점부터 잰다.
  - 429/503이면 Retry-After를 따르고 간격을 2배로 늘린다.
  - 403·3xx·5xx가 오면 즉시 중지한다.
  - 나쁜 응답이 연속 3회면 중지한다.
- **ALIO 엔드포인트:**
  - `GET https://www.alio.go.kr/occasional/findRuleList.json?type=apbaNa&word={기관명}&pageNo={n}`
  - `GET /occasional/findRuleDtl.json?seq={seq}`
  - `GET /download/rulefiledown.json?fileNo={fileNo}`
- **law.go.kr 엔드포인트:**
  - `GET https://www.law.go.kr/DRF/lawSearch.do?OC={oc}&target=law&type=XML&display=100&query={q}`
  - `GET /DRF/lawService.do?OC={oc}&target=law&MST={mst}&type=XML`
- **outbox 토픽:** `regulation.source_fetched`, `regulation.law_fetched`
- **파일 허용 형식:** 그 밖의 형식은 거부(`rejected`)로 기록하고 저장하지 않는다.
  - PDF: `%PDF`로 시작
  - HWP 5.0: OLE 매직 `D0 CF 11 E0 A1 B1 1A E1`
  - HWPX: `PK\x03\x04`이고 파일명이 `.hwpx`로 끝남
- **User-Agent:** `NST-Regulation-Collector/0.1 (+contact: bigdatanigel1513@gmail.com)`

## Review Focus

1. **`bFiles`의 파일명에 쉼표가 들어간 경우** (`"1|a,b.pdf,2|c.pdf"`). 파일 2개로 정확히 나뉘어야 한다. 이를 위해 `,(?=\d+\|)` 기준으로 나눈다. Task 5에서 테스트한다.
2. **기관명 검색에 다른 기관이 섞이는 경우.** `apbaNa` 검색은 부분 일치라서, 수집 대상은 `apbaId`가 일치하는 행만이어야 한다. Task 6에서 테스트한다.
3. **다운로드 응답이 파일이 아닌 경우.** ALIO가 오류 HTML을 200으로 줄 수 있다. 이때는 `alio_rule_file.status='rejected'`로 기록하고, blob과 이벤트를 만들지 않는다. Task 6에서 테스트한다.
4. **같은 내용의 파일이 새 `fileNo`로 다시 올라온 경우.** 파일 매핑은 기록한다. 하지만 blob을 중복 저장하지 않고, `source_fetched` 이벤트도 내지 않는다(새 내용이 아니므로). Task 6에서 테스트한다.
5. **수집 도중 중지되거나 오류가 난 경우.** 규정 단위로 커밋하므로, 다시 실행하면 이미 받은 파일은 건너뛰고 나머지만 받아야 한다. `fetch_run.status`는 `failed`로 남는다. Task 6에서 테스트한다.

---

## File Structure

```
nst-regulation/
├── pyproject.toml                 # 의존성, pytest 설정, reg 콘솔 스크립트
├── .env.example                   # 환경변수 목록 (비밀값 없음)
├── alembic.ini
├── config/
│   ├── institutions.yaml          # 수집 대상 기관 (code, name, kind, alio_apba_id, alio_name)
│   └── laws.yaml                  # 핵심 법령 시드 이름
├── src/reg/
│   ├── __init__.py
│   ├── settings.py                # Settings (pydantic-settings)
│   ├── db/
│   │   ├── __init__.py
│   │   ├── bootstrap.py           # 역할·스키마 생성 (슈퍼유저)
│   │   └── conn.py                # connect(dsn) -> psycopg.Connection (dict_row)
│   ├── migrations/                # Alembic env + versions
│   │   ├── env.py
│   │   ├── script.py.mako
│   │   └── versions/0001_collect.py
│   ├── storage/
│   │   ├── __init__.py
│   │   └── blob.py                # BlobStore, LocalBlobStore, S3BlobStore, blob_key()
│   ├── collect/
│   │   ├── __init__.py
│   │   ├── polite.py              # PoliteClient, StopCollecting
│   │   ├── sniff.py               # sniff(content, filename) -> FileKind | None
│   │   ├── archive.py             # store() -> StoredDoc
│   │   ├── runs.py                # start_run / finish_run / request logger
│   │   ├── alio.py                # AlioClient + parse_bfiles
│   │   ├── alio_sync.py           # load_institutions, sync_institution
│   │   ├── lawgo.py               # LawGoClient, parse_search
│   │   └── law_sync.py            # sync_laws
│   ├── outbox.py                  # write(conn, topic, payload)
│   └── cli.py                     # typer app: db / bucket / collect
└── tests/
    ├── conftest.py                # pg 컨테이너, migrated_conn, blob 픽스처
    ├── fixtures/                  # 실제 응답 기록 (2026-10-02)
    │   ├── alio_list_kasi_p1.json
    │   ├── alio_detail.json
    │   ├── lawgo_search.xml
    │   └── lawgo_service_283849.xml
    ├── test_settings.py
    ├── test_migrations.py
    ├── test_blob.py
    ├── test_polite.py
    ├── test_sniff_archive.py
    ├── test_alio.py
    ├── test_alio_sync.py
    ├── test_lawgo.py
    └── test_cli_smoke.py
```

---

### Task 1: 프로젝트 골격과 설정

**Files:**
- Create: `pyproject.toml`, `.env.example`, `src/reg/__init__.py`, `src/reg/settings.py`, `tests/test_settings.py`
- Modify: `.gitignore` (`.pytest_cache/` 추가)

**Interfaces:**
- Produces:
  - `reg.settings.Settings` (필드는 아래 코드 참고)
  - `reg.settings.get_settings() -> Settings` (lru_cache)

- [ ] **Step 1: pyproject와 .env.example 작성**

```toml
# pyproject.toml
[project]
name = "nst-regulation"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
  "httpx>=0.27",
  "psycopg[binary]>=3.2",
  "alembic>=1.13",
  "sqlalchemy>=2.0",
  "pydantic-settings>=2.4",
  "boto3>=1.34",
  "pyyaml>=6.0",
  "typer>=0.12",
]

[project.scripts]
reg = "reg.cli:app"

[dependency-groups]
dev = ["pytest>=8", "respx>=0.21", "testcontainers[postgres]>=4.8", "ruff>=0.6"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/reg"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["integration: needs live shared infrastructure"]
addopts = "-m 'not integration'"
```

```bash
# .env.example
REG_DATABASE_URL=postgresql://reg_app:CHANGE_ME@127.0.0.1:21055/nais
REG_MIGRATOR_URL=postgresql://reg_migrator:CHANGE_ME@127.0.0.1:21055/nais
REG_S3_ENDPOINT=http://127.0.0.1:21053
REG_S3_BUCKET=regulation
REG_S3_ACCESS_KEY=CHANGE_ME
REG_S3_SECRET_KEY=CHANGE_ME
REG_LAWGO_OC=CHANGE_ME
REG_ALIO_MIN_INTERVAL=1.5
REG_LAWGO_MIN_INTERVAL=1.0
```

- [ ] **Step 2: 실패하는 테스트 작성**

```python
# tests/test_settings.py
from reg.settings import Settings


def test_settings_read_env(monkeypatch):
    monkeypatch.setenv("REG_DATABASE_URL", "postgresql://a:b@h:1/d")
    monkeypatch.setenv("REG_LAWGO_OC", "oc1")
    s = Settings(_env_file=None)
    assert s.database_url == "postgresql://a:b@h:1/d"
    assert s.lawgo_oc == "oc1"
    assert s.alio_min_interval == 1.5
    assert s.s3_bucket == "regulation"
```

- [ ] **Step 3: 테스트가 실패하는지 확인**

Run: `uv sync && uv run pytest tests/test_settings.py -v`
Expected: FAIL (`ModuleNotFoundError: reg.settings`)

- [ ] **Step 4: Settings 구현**

```python
# src/reg/__init__.py
```

```python
# src/reg/settings.py
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

USER_AGENT = "NST-Regulation-Collector/0.1 (+contact: bigdatanigel1513@gmail.com)"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REG_", env_file=".env", extra="ignore")

    database_url: str = "postgresql://reg_app:reg@127.0.0.1:21055/nais"
    migrator_url: str = "postgresql://reg_migrator:reg@127.0.0.1:21055/nais"
    s3_endpoint: str = "http://127.0.0.1:21053"
    s3_bucket: str = "regulation"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    lawgo_oc: str = ""
    alio_min_interval: float = 1.5
    lawgo_min_interval: float = 1.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 5: 테스트 통과 확인 후 커밋**

Run: `uv run pytest tests/test_settings.py -v` → PASS

```bash
git add pyproject.toml uv.lock .env.example .gitignore src/reg tests/test_settings.py
git commit -m "feat: project skeleton and settings"
```

---

### Task 2: DB bootstrap과 M1 마이그레이션

**Files:**
- Create: `src/reg/db/__init__.py`, `src/reg/db/bootstrap.py`, `src/reg/db/conn.py`, `alembic.ini`, `src/reg/migrations/env.py`, `src/reg/migrations/script.py.mako`, `src/reg/migrations/versions/0001_collect.py`, `tests/conftest.py`, `tests/test_migrations.py`

**Interfaces:**
- Produces:
  - `reg.db.bootstrap.bootstrap(superuser_dsn: str, db_name: str, migrator_password: str, app_password: str) -> None`
    - 역할 `reg_migrator`와 `reg_app`을 만든다.
    - 스키마 `regulation`을 만들고 기본 권한을 설정한다.
    - 여러 번 실행해도 결과가 같다(멱등).
  - `reg.db.conn.connect(dsn: str) -> psycopg.Connection` (`row_factory=dict_row`, `autocommit=False`)
  - `reg.db.migrate.upgrade(migrator_dsn: str) -> None`. 위치는 `src/reg/db/bootstrap.py` 옆의 `migrate.py`다.
  - 테스트 픽스처 `migrated(pg)`. `(app_dsn, migrator_dsn)`을 돌려준다.
  - 테이블 (모두 `regulation.` 접두): `institution`, `fetch_run`, `request_log`, `source_document`, `alio_rule`, `alio_rule_file`, `law_watch`, `outbox`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/conftest.py
import pytest
from testcontainers.postgres import PostgresContainer

from reg.db.bootstrap import bootstrap
from reg.db.migrate import upgrade


def _dsn(c: PostgresContainer, user: str, pw: str) -> str:
    host, port = c.get_container_host_ip(), c.get_exposed_port(5432)
    return f"postgresql://{user}:{pw}@{host}:{port}/{c.dbname}"


@pytest.fixture(scope="session")
def pg():
    with PostgresContainer("postgres:16", username="su", password="su", dbname="nais") as c:
        yield c


@pytest.fixture(scope="session")
def migrated(pg):
    su = _dsn(pg, "su", "su")
    bootstrap(su, "nais", "mig", "app")
    mig, app = _dsn(pg, "reg_migrator", "mig"), _dsn(pg, "reg_app", "app")
    upgrade(mig)
    return app, mig


@pytest.fixture
def conn(migrated):
    from reg.db.conn import connect

    c = connect(migrated[0])
    yield c
    c.rollback()
    with c.cursor() as cur:  # 테스트 간 격리: 데이터만 비운다
        cur.execute(
            "TRUNCATE regulation.outbox, regulation.alio_rule_file, regulation.alio_rule,"
            " regulation.law_watch, regulation.request_log, regulation.fetch_run,"
            " regulation.source_document, regulation.institution RESTART IDENTITY CASCADE"
        )
    c.commit()
    c.close()
```

```python
# tests/test_migrations.py
from reg.db.bootstrap import bootstrap

TABLES = {"institution", "fetch_run", "request_log", "source_document",
          "alio_rule", "alio_rule_file", "law_watch", "outbox"}


def test_tables_exist_and_app_can_write(conn):
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='regulation'"
    ).fetchall()
    assert TABLES <= {r["table_name"] for r in rows}
    conn.execute("INSERT INTO regulation.outbox (topic, payload) VALUES ('t', '{}')")


def test_app_cannot_create_tables(conn):
    import psycopg
    import pytest

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("CREATE TABLE regulation.nope (x int)")


def test_bootstrap_is_idempotent(pg, migrated):
    from tests.conftest import _dsn

    bootstrap(_dsn(pg, "su", "su"), "nais", "mig", "app")  # 두 번째 실행도 오류 없음
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `uv run pytest tests/test_migrations.py -v`
Expected: FAIL (`ModuleNotFoundError: reg.db.bootstrap`)

- [ ] **Step 3: bootstrap, conn, migrate 구현**

```python
# src/reg/db/__init__.py
```

```python
# src/reg/db/conn.py
import psycopg
from psycopg.rows import dict_row


def connect(dsn: str) -> psycopg.Connection:
    return psycopg.connect(dsn, row_factory=dict_row)
```

```python
# src/reg/db/bootstrap.py
"""공유 Postgres에 이 프로젝트 전용 역할·스키마를 만든다. 슈퍼유저 DSN으로 한 번 실행한다 (멱등)."""
import psycopg
from psycopg import sql


def _ensure_role(cur, name: str, password: str) -> None:
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (name,))
    verb = "ALTER" if cur.fetchone() else "CREATE"
    cur.execute(sql.SQL(verb + " ROLE {} LOGIN PASSWORD {}").format(
        sql.Identifier(name), sql.Literal(password)))


def bootstrap(superuser_dsn: str, db_name: str, migrator_password: str, app_password: str) -> None:
    with psycopg.connect(superuser_dsn, autocommit=True) as c, c.cursor() as cur:
        _ensure_role(cur, "reg_migrator", migrator_password)
        _ensure_role(cur, "reg_app", app_password)
        db = sql.Identifier(db_name)
        cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO reg_migrator, reg_app").format(db))
        cur.execute("CREATE SCHEMA IF NOT EXISTS regulation AUTHORIZATION reg_migrator")
        cur.execute("GRANT USAGE ON SCHEMA regulation TO reg_app")
        cur.execute("ALTER DEFAULT PRIVILEGES FOR ROLE reg_migrator IN SCHEMA regulation"
                    " GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON TABLES TO reg_app")
        cur.execute("ALTER DEFAULT PRIVILEGES FOR ROLE reg_migrator IN SCHEMA regulation"
                    " GRANT USAGE, SELECT ON SEQUENCES TO reg_app")
```

```python
# src/reg/db/migrate.py
from pathlib import Path

from alembic import command
from alembic.config import Config

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


def alembic_config(migrator_dsn: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    cfg.set_main_option("sqlalchemy.url", migrator_dsn.replace("postgresql://", "postgresql+psycopg://", 1))
    return cfg


def upgrade(migrator_dsn: str, revision: str = "head") -> None:
    command.upgrade(alembic_config(migrator_dsn), revision)
```

- [ ] **Step 4: Alembic env와 0001 마이그레이션 작성**

```ini
# alembic.ini  (CLI 직접 사용 시; 코드는 reg.db.migrate를 쓴다)
[alembic]
script_location = src/reg/migrations
```

```python
# src/reg/migrations/env.py
from alembic import context
from sqlalchemy import create_engine

url = context.config.get_main_option("sqlalchemy.url")
engine = create_engine(url)
with engine.connect() as connection:
    context.configure(connection=connection, version_table_schema="regulation")
    with context.begin_transaction():
        context.run_migrations()
```

```mako
## src/reg/migrations/script.py.mako
"""${message}"""
from alembic import op

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

```python
# src/reg/migrations/versions/0001_collect.py
"""M1 수집 테이블"""
from alembic import op

revision = "0001"
down_revision = None

DDL = """
CREATE TABLE regulation.institution (
  id serial PRIMARY KEY,
  code text NOT NULL UNIQUE,
  name text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('NST', 'GRI')),
  alio_apba_id text UNIQUE,
  alio_name text,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE regulation.fetch_run (
  id bigserial PRIMARY KEY,
  source text NOT NULL,
  scope text,
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  status text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'succeeded', 'failed')),
  stats jsonb NOT NULL DEFAULT '{}',
  error text
);
CREATE TABLE regulation.request_log (
  id bigserial PRIMARY KEY,
  run_id bigint REFERENCES regulation.fetch_run(id),
  source text NOT NULL,
  url text NOT NULL,
  status int,
  bytes int,
  elapsed_ms int,
  waited_ms int,
  error text,
  at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE regulation.source_document (
  id bigserial PRIMARY KEY,
  source text NOT NULL CHECK (source IN ('alio', 'lawgo')),
  sha256 text NOT NULL,
  blob_key text NOT NULL,
  mime text NOT NULL,
  size_bytes bigint NOT NULL,
  url text NOT NULL,
  fetched_at timestamptz NOT NULL DEFAULT now(),
  source_meta jsonb NOT NULL DEFAULT '{}',
  UNIQUE (source, sha256)
);
CREATE TABLE regulation.alio_rule (
  seq text PRIMARY KEY,
  institution_id int NOT NULL REFERENCES regulation.institution(id),
  title text NOT NULL,
  divis text,
  revised_on date,
  posted_on date,
  list_fingerprint text,
  detail jsonb NOT NULL DEFAULT '{}',
  first_seen_at timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE regulation.alio_rule_file (
  file_no text PRIMARY KEY,
  seq text NOT NULL REFERENCES regulation.alio_rule(seq),
  file_name text NOT NULL,
  ord int NOT NULL,
  status text NOT NULL CHECK (status IN ('fetched', 'rejected')),
  reject_reason text,
  source_document_id bigint REFERENCES regulation.source_document(id),
  fetched_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE regulation.law_watch (
  law_id text PRIMARY KEY,
  name text NOT NULL,
  kind text,
  last_mst text,
  promulgated_on date,
  effective_on date,
  source_document_id bigint REFERENCES regulation.source_document(id),
  last_checked_at timestamptz
);
CREATE TABLE regulation.outbox (
  id bigserial PRIMARY KEY,
  topic text NOT NULL,
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  claimed_at timestamptz,
  processed_at timestamptz,
  attempts int NOT NULL DEFAULT 0
);
CREATE INDEX outbox_unprocessed ON regulation.outbox (id) WHERE processed_at IS NULL;
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    for t in ["outbox", "law_watch", "alio_rule_file", "alio_rule", "source_document",
              "request_log", "fetch_run", "institution"]:
        op.execute(f"DROP TABLE regulation.{t}")
```

- [ ] **Step 5: 테스트 통과 확인 후 커밋**

Run: `uv run pytest tests/test_migrations.py -v` → 3 PASS

```bash
git add alembic.ini src/reg/db src/reg/migrations tests/conftest.py tests/test_migrations.py
git commit -m "feat(db): bootstrap roles/schema and M1 collection tables"
```

---

### Task 3: BlobStore (로컬·S3)

**Files:**
- Create: `src/reg/storage/__init__.py`, `src/reg/storage/blob.py`, `tests/test_blob.py`

**Interfaces:**
- Produces:
  - `blob_key(source: str, sha256: str, ext: str) -> str`. 형식은 `raw/{source}/{sha[:2]}/{sha}.{ext}`다.
  - `class BlobStore(Protocol)`: `put(key: str, data: bytes, content_type: str) -> None`, `get(key: str) -> bytes`, `exists(key: str) -> bool`
  - `LocalBlobStore(root: Path)`
  - `S3BlobStore(endpoint, bucket, access_key, secret_key)`
    - 생성자는 연결만 하고 버킷을 만들지 않는다.
    - 버킷 생성은 `ensure_bucket() -> None`이 맡는다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_blob.py
import os

import pytest

from reg.storage.blob import LocalBlobStore, S3BlobStore, blob_key


def test_blob_key_layout():
    assert blob_key("alio", "abcdef", "pdf") == "raw/alio/ab/abcdef.pdf"


def test_local_roundtrip(tmp_path):
    s = LocalBlobStore(tmp_path)
    assert not s.exists("raw/x/ab/abc.pdf")
    s.put("raw/x/ab/abc.pdf", b"%PDF-1", "application/pdf")
    assert s.exists("raw/x/ab/abc.pdf")
    assert s.get("raw/x/ab/abc.pdf") == b"%PDF-1"


@pytest.mark.integration
def test_s3_roundtrip_live():
    from reg.settings import get_settings

    st = get_settings()
    s = S3BlobStore(st.s3_endpoint, st.s3_bucket, st.s3_access_key, st.s3_secret_key)
    s.ensure_bucket()
    s.put("test/hello.txt", b"hi", "text/plain")
    assert s.exists("test/hello.txt") and s.get("test/hello.txt") == b"hi"
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `uv run pytest tests/test_blob.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: 구현**

```python
# src/reg/storage/__init__.py
```

```python
# src/reg/storage/blob.py
from pathlib import Path
from typing import Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


def blob_key(source: str, sha256: str, ext: str) -> str:
    return f"raw/{source}/{sha256[:2]}/{sha256}.{ext}"


class BlobStore(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def get(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...


class LocalBlobStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        p = self.root / key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get(self, key: str) -> bytes:
        return (self.root / key).read_bytes()

    def exists(self, key: str) -> bool:
        return (self.root / key).exists()


class S3BlobStore:
    def __init__(self, endpoint: str, bucket: str, access_key: str, secret_key: str):
        self.bucket = bucket
        self.s3 = boto3.client(
            "s3", endpoint_url=endpoint, aws_access_key_id=access_key,
            aws_secret_access_key=secret_key, region_name="us-east-1",
            config=Config(s3={"addressing_style": "path"}, signature_version="s3v4"),
        )

    def ensure_bucket(self) -> None:
        try:
            self.s3.head_bucket(Bucket=self.bucket)
        except ClientError:
            self.s3.create_bucket(Bucket=self.bucket)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def get(self, key: str) -> bytes:
        return self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def exists(self, key: str) -> bool:
        try:
            self.s3.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False
```

- [ ] **Step 4: 테스트 통과 확인 후 커밋**

Run: `uv run pytest tests/test_blob.py -v` → 2 PASS (integration 1건 제외)

```bash
git add src/reg/storage tests/test_blob.py
git commit -m "feat(storage): content-addressed blob store (local, S3)"
```

---

### Task 4: PoliteClient와 수집 실행 기록

**Files:**
- Create: `src/reg/collect/__init__.py`, `src/reg/collect/polite.py`, `src/reg/collect/runs.py`, `tests/test_polite.py`

**Interfaces:**
- Produces:
  - `class StopCollecting(Exception)`
  - `PoliteClient(source: str, min_interval: float, log: Callable[[RequestLog], None] | None = None, max_bad: int = 3, timeout: float = 60.0, sleep: Callable[[float], None] = time.sleep)`
    - `.get(url: str, params: dict | None = None) -> httpx.Response`
    - `.close()`
  - `@dataclass RequestLog(source, url, status: int | None, bytes: int | None, elapsed_ms: int, waited_ms: int, error: str | None)`
  - `runs.start_run(conn, source: str, scope: str | None) -> int`
  - `runs.finish_run(conn, run_id: int, status: str, stats: dict, error: str | None = None) -> None`
  - `runs.db_logger(conn, run_id) -> Callable[[RequestLog], None]`
    - 매 요청을 `request_log`에 INSERT한다.
    - 커밋은 하지 않는다. 호출자가 규정 단위로 커밋한다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_polite.py
import httpx
import pytest
import respx

from reg.collect.polite import PoliteClient, StopCollecting


def make(**kw):
    slept, logs = [], []
    c = PoliteClient("t", min_interval=1.5, log=logs.append, sleep=slept.append, **kw)
    return c, slept, logs


@respx.mock
def test_waits_min_interval_between_requests():
    respx.get("https://x/a").respond(200, text="ok")
    c, slept, logs = make()
    c.get("https://x/a")
    c.get("https://x/a")
    assert len(slept) == 1 and 0 < slept[0] <= 1.5
    assert [l.status for l in logs] == [200, 200]


@respx.mock
def test_429_follows_retry_after_and_doubles_interval():
    route = respx.get("https://x/a")
    route.side_effect = [httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200, text="ok")]
    c, slept, _ = make()
    assert c.get("https://x/a").status_code == 200
    assert 7 in slept and c.min_interval == 3.0


@respx.mock
def test_403_stops_immediately():
    respx.get("https://x/a").respond(403)
    c, _, _ = make()
    with pytest.raises(StopCollecting):
        c.get("https://x/a")


@respx.mock
def test_three_bad_in_a_row_stops():
    respx.get("https://x/a").respond(503)
    c, _, _ = make()
    with pytest.raises(StopCollecting):
        c.get("https://x/a")


@respx.mock
def test_params_are_sent():
    route = respx.get("https://x/a", params={"q": "여비"}).respond(200)
    c, _, _ = make()
    c.get("https://x/a", params={"q": "여비"})
    assert route.called
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `uv run pytest tests/test_polite.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: 구현**

```python
# src/reg/collect/__init__.py
```

```python
# src/reg/collect/polite.py
"""출처 규칙을 강제하는 HTTP 클라이언트 (world_law_collect/wlc/polite.py 이식).

- 출처당 요청 1개씩, 응답 완료 시점 기준 최소 간격 보장
- 429/503: Retry-After를 따르고 간격을 두 배로
- 403, 3xx, 5xx(503 제외): 즉시 중지 / 나쁜 응답 연속 max_bad회: 중지
"""
import time
from dataclasses import dataclass
from typing import Callable

import httpx

from reg.settings import USER_AGENT


class StopCollecting(Exception):
    """차단 위험 신호. 수집을 즉시 멈춰야 한다."""


@dataclass
class RequestLog:
    source: str
    url: str
    status: int | None
    bytes: int | None
    elapsed_ms: int
    waited_ms: int
    error: str | None = None


class PoliteClient:
    def __init__(self, source: str, min_interval: float, log: Callable[[RequestLog], None] | None = None,
                 max_bad: int = 3, timeout: float = 60.0, sleep: Callable[[float], None] = time.sleep):
        self.source = source
        self.min_interval = min_interval
        self.max_bad = max_bad
        self.bad_streak = 0
        self._log = log or (lambda _: None)
        self._sleep = sleep
        self._last_done: float | None = None
        self.client = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=timeout,
                                   follow_redirects=False)

    def get(self, url: str, params: dict | None = None) -> httpx.Response:
        waited = 0.0
        if self._last_done is not None:
            waited = self.min_interval - (time.monotonic() - self._last_done)
            if waited > 0:
                self._sleep(waited)
            waited = max(waited, 0.0)
        t0 = time.monotonic()
        try:
            resp = self.client.get(url, params=params)
        except httpx.HTTPError as e:
            self._last_done = time.monotonic()
            self._log(RequestLog(self.source, url, None, None, int((self._last_done - t0) * 1000),
                                 int(waited * 1000), repr(e)))
            self._bad(f"네트워크 오류 {e!r}")
            raise
        self._last_done = time.monotonic()
        self._log(RequestLog(self.source, str(resp.request.url), resp.status_code, len(resp.content),
                             int((self._last_done - t0) * 1000), int(waited * 1000)))

        if resp.status_code in (429, 503):
            self._bad(f"HTTP {resp.status_code}")
            retry = resp.headers.get("Retry-After", "")
            self._sleep(min(float(retry) if retry.isdigit() else 60.0, 600.0))
            self.min_interval *= 2
            return self.get(url, params)
        if resp.status_code == 403 or resp.status_code >= 500 or 300 <= resp.status_code < 400:
            raise StopCollecting(f"{self.source}: HTTP {resp.status_code} — 차단 위험 신호로 중지")
        self.bad_streak = 0
        return resp

    def _bad(self, why: str) -> None:
        self.bad_streak += 1
        if self.bad_streak >= self.max_bad:
            raise StopCollecting(f"{self.source}: {why} 연속 {self.bad_streak}회 — 중지")

    def close(self) -> None:
        self.client.close()
```

```python
# src/reg/collect/runs.py
import json
from typing import Callable

from reg.collect.polite import RequestLog


def start_run(conn, source: str, scope: str | None) -> int:
    row = conn.execute("INSERT INTO regulation.fetch_run (source, scope) VALUES (%s, %s) RETURNING id",
                       (source, scope)).fetchone()
    conn.commit()
    return row["id"]


def finish_run(conn, run_id: int, status: str, stats: dict, error: str | None = None) -> None:
    conn.rollback()  # 실패한 규정의 미커밋 변경은 버린다
    conn.execute("UPDATE regulation.fetch_run SET finished_at = now(), status = %s, stats = %s, error = %s"
                 " WHERE id = %s", (status, json.dumps(stats, ensure_ascii=False), error, run_id))
    conn.commit()


def db_logger(conn, run_id: int) -> Callable[[RequestLog], None]:
    def log(r: RequestLog) -> None:
        conn.execute("INSERT INTO regulation.request_log (run_id, source, url, status, bytes, elapsed_ms,"
                     " waited_ms, error) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                     (run_id, r.source, r.url, r.status, r.bytes, r.elapsed_ms, r.waited_ms, r.error))
    return log
```

- [ ] **Step 4: 테스트 통과 확인 후 커밋**

Run: `uv run pytest tests/test_polite.py -v` → 5 PASS

```bash
git add src/reg/collect/__init__.py src/reg/collect/polite.py src/reg/collect/runs.py tests/test_polite.py
git commit -m "feat(collect): polite HTTP client and fetch run logging"
```

---

### Task 5: 파일 판별, 원본 보관, outbox, ALIO 클라이언트

**Files:**
- Create: `src/reg/collect/sniff.py`, `src/reg/collect/archive.py`, `src/reg/outbox.py`, `src/reg/collect/alio.py`, `tests/fixtures/alio_list_kasi_p1.json`, `tests/fixtures/alio_detail.json`, `tests/test_sniff_archive.py`, `tests/test_alio.py`

**Interfaces:**
- Produces:
  - `sniff.FileKind(mime: str, ext: str)` (NamedTuple)
  - `sniff.sniff(content: bytes, filename: str) -> FileKind | None`
  - `archive.StoredDoc(id: int, sha256: str, blob_key: str, is_new: bool)` (dataclass)
  - `archive.store(conn, blob: BlobStore, *, source: str, url: str, content: bytes, kind: FileKind, meta: dict) -> StoredDoc`
    - 같은 `(source, sha256)`이 이미 있으면 기존 행을 돌려준다(`is_new=False`).
    - blob은 키가 없을 때만 저장한다.
  - `outbox.write(conn, topic: str, payload: dict) -> int`
  - `alio.parse_bfiles(s: str | None) -> list[tuple[str, str]]` (fileNo, fileName)
  - `alio.ListRow(seq, title, apba_id, divis, fingerprint)`
  - `alio.RuleDetail(seq, title, divis, revised_on: date | None, posted_on: date | None, files: list[tuple[str, str]], raw: dict)`
  - `alio.AlioClient(http: PoliteClient, base: str = "https://www.alio.go.kr")`
    - `.list_rules(alio_name: str, apba_id: str) -> Iterator[ListRow]`: 모든 페이지를 돌고 `apbaId`가 일치하는 행만 낸다.
    - `.detail(seq: str) -> RuleDetail`
    - `.download(file_no: str) -> bytes`
  - `alio.AlioError(Exception)`: JSON이 아니거나 `status != success`일 때

- [ ] **Step 1: 실제 응답 픽스처 기록**

Run (한 번만; 2026-10-02 기록본을 저장소에 커밋):

```bash
mkdir -p tests/fixtures
uv run python - <<'EOF'
import json, time, httpx
H = {"User-Agent": "NST-Regulation-Collector/0.1 (+contact: bigdatanigel1513@gmail.com)"}
L = httpx.get("https://www.alio.go.kr/occasional/findRuleList.json",
              params={"type": "apbaNa", "word": "한국천문연구원", "pageNo": 1}, headers=H).json()
L["data"]["result"] = L["data"]["result"][:3]
L["data"]["page"]["totalPage"] = 1
json.dump(L, open("tests/fixtures/alio_list_kasi_p1.json", "w"), ensure_ascii=False, indent=1)
time.sleep(1.5)
D = httpx.get("https://www.alio.go.kr/occasional/findRuleDtl.json", params={"seq": "47852"}, headers=H).json()
json.dump(D, open("tests/fixtures/alio_detail.json", "w"), ensure_ascii=False, indent=1)
EOF
```

기록된 내용 중 테스트가 기대하는 값은 다음과 같다.
- 목록: `seq` 47852 / 10619 / 10570, `apbaId` C0266
- 상세(47852): `retryRvsnYmd` "2024.01.17", `idate` "2022.05.25", `insdRuleDivis` "인사·복무·징계"
- `bFiles`: `"151446|한국천문연구원 스쿨운영규정(2022년 5월 제정).pdf,186628|한국천문연구원 스쿨운영규정(2024년도 1월 개정).pdf"`

- [ ] **Step 2: 실패하는 테스트 작성**

```python
# tests/test_sniff_archive.py
from reg.collect.archive import store
from reg.collect.sniff import sniff
from reg.storage.blob import LocalBlobStore

OLE = bytes.fromhex("D0CF11E0A1B11AE1") + b"\x00" * 8


def test_sniff_kinds():
    assert sniff(b"%PDF-1.4 ...", "a.pdf").ext == "pdf"
    assert sniff(OLE, "a.hwp").ext == "hwp"
    assert sniff(b"PK\x03\x04....", "a.hwpx").ext == "hwpx"
    assert sniff(b"PK\x03\x04....", "a.zip") is None
    assert sniff(b"<html>error</html>", "a.pdf") is None
    assert sniff(b"", "a.pdf") is None


def test_store_dedupes_by_content(conn, tmp_path):
    blob = LocalBlobStore(tmp_path)
    k = sniff(b"%PDF-1.4 x", "a.pdf")
    a = store(conn, blob, source="alio", url="u1", content=b"%PDF-1.4 x", kind=k, meta={"f": 1})
    b = store(conn, blob, source="alio", url="u2", content=b"%PDF-1.4 x", kind=k, meta={"f": 2})
    assert a.is_new and not b.is_new and a.id == b.id
    assert blob.get(a.blob_key) == b"%PDF-1.4 x"
    assert conn.execute("SELECT count(*) AS n FROM regulation.source_document").fetchone()["n"] == 1
```

```python
# tests/test_alio.py
import json
from datetime import date
from pathlib import Path

import pytest
import respx

from reg.collect.alio import AlioClient, AlioError, parse_bfiles
from reg.collect.polite import PoliteClient

FX = Path(__file__).parent / "fixtures"
BASE = "https://www.alio.go.kr"


def client():
    return AlioClient(PoliteClient("alio", 0, sleep=lambda s: None))


def test_parse_bfiles_handles_commas_in_names():
    assert parse_bfiles("1|a,b.pdf,22|c.pdf") == [("1", "a,b.pdf"), ("22", "c.pdf")]
    assert parse_bfiles("") == [] and parse_bfiles(None) == []


@respx.mock
def test_list_rules_filters_by_apba_id():
    data = json.loads((FX / "alio_list_kasi_p1.json").read_text())
    data["data"]["result"][2]["apbaId"] = "C9999"  # 부분일치로 섞여 들어온 다른 기관
    respx.get(f"{BASE}/occasional/findRuleList.json").respond(200, json=data)
    rows = list(client().list_rules("한국천문연구원", "C0266"))
    assert [r.seq for r in rows] == ["47852", "10619"]
    assert rows[0].fingerprint  # submissionNo|ruleStDa


@respx.mock
def test_detail_parses_dates_and_files():
    respx.get(f"{BASE}/occasional/findRuleDtl.json").respond(
        200, json=json.loads((FX / "alio_detail.json").read_text()))
    d = client().detail("47852")
    assert d.revised_on == date(2024, 1, 17) and d.posted_on == date(2022, 5, 25)
    assert d.divis == "인사·복무·징계"
    assert [f[0] for f in d.files] == ["151446", "186628"]


@respx.mock
def test_non_json_response_raises():
    respx.get(f"{BASE}/occasional/findRuleDtl.json").respond(200, text="<html>점검중</html>")
    with pytest.raises(AlioError):
        client().detail("1")
```

- [ ] **Step 3: 테스트가 실패하는지 확인**

Run: `uv run pytest tests/test_sniff_archive.py tests/test_alio.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 4: 구현**

```python
# src/reg/collect/sniff.py
from typing import NamedTuple

OLE_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")


class FileKind(NamedTuple):
    mime: str
    ext: str


def sniff(content: bytes, filename: str) -> FileKind | None:
    """허용 형식(PDF, HWP 5.0, HWPX)만 인정한다. 오류 페이지나 기타 형식은 None."""
    name = filename.lower()
    if content.startswith(b"%PDF"):
        return FileKind("application/pdf", "pdf")
    if content.startswith(OLE_MAGIC):
        return FileKind("application/x-hwp", "hwp")
    if content.startswith(b"PK\x03\x04") and name.endswith(".hwpx"):
        return FileKind("application/hwp+zip", "hwpx")
    return None
```

```python
# src/reg/outbox.py
import json


def write(conn, topic: str, payload: dict) -> int:
    row = conn.execute("INSERT INTO regulation.outbox (topic, payload) VALUES (%s, %s) RETURNING id",
                       (topic, json.dumps(payload, ensure_ascii=False))).fetchone()
    return row["id"]
```

```python
# src/reg/collect/archive.py
"""원본 보관: 내용 주소(SHA-256) 방식. 같은 내용은 blob 1개, source_document 1행."""
import hashlib
import json
from dataclasses import dataclass

from reg.collect.sniff import FileKind
from reg.storage.blob import BlobStore, blob_key


@dataclass
class StoredDoc:
    id: int
    sha256: str
    blob_key: str
    is_new: bool


def store(conn, blob: BlobStore, *, source: str, url: str, content: bytes, kind: FileKind,
          meta: dict) -> StoredDoc:
    sha = hashlib.sha256(content).hexdigest()
    row = conn.execute("SELECT id, blob_key FROM regulation.source_document WHERE source = %s AND sha256 = %s",
                       (source, sha)).fetchone()
    if row:
        return StoredDoc(row["id"], sha, row["blob_key"], False)
    key = blob_key(source, sha, kind.ext)
    if not blob.exists(key):
        blob.put(key, content, kind.mime)
    row = conn.execute(
        "INSERT INTO regulation.source_document (source, sha256, blob_key, mime, size_bytes, url, source_meta)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (source, sha, key, kind.mime, len(content), url, json.dumps(meta, ensure_ascii=False)),
    ).fetchone()
    return StoredDoc(row["id"], sha, key, True)
```

```python
# src/reg/collect/alio.py
"""ALIO 내부규정 공시 클라이언트 (엔드포인트 2026-10-01 확인)."""
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Iterator

from reg.collect.polite import PoliteClient

_BFILE_SPLIT = re.compile(r",(?=\d+\|)")


class AlioError(Exception):
    """ALIO가 정상 JSON을 주지 않음 (점검, 오류 페이지 등)."""


def parse_bfiles(s: str | None) -> list[tuple[str, str]]:
    if not s:
        return []
    out = []
    for part in _BFILE_SPLIT.split(s):
        no, _, name = part.partition("|")
        if no.strip() and name:
            out.append((no.strip(), name))
    return out


def _date(s: str | None) -> date | None:
    m = re.match(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", s or "")
    return date(int(m[1]), int(m[2]), int(m[3])) if m else None


@dataclass
class ListRow:
    seq: str
    title: str
    apba_id: str
    divis: str | None
    fingerprint: str


@dataclass
class RuleDetail:
    seq: str
    title: str
    divis: str | None
    revised_on: date | None
    posted_on: date | None
    files: list[tuple[str, str]]
    raw: dict = field(repr=False)


class AlioClient:
    def __init__(self, http: PoliteClient, base: str = "https://www.alio.go.kr"):
        self.http = http
        self.base = base

    def _json(self, path: str, params: dict) -> dict:
        resp = self.http.get(self.base + path, params=params)
        try:
            body = resp.json()
        except ValueError as e:
            raise AlioError(f"{path}: JSON 아님 ({resp.text[:80]!r})") from e
        if body.get("status") != "success":
            raise AlioError(f"{path}: status={body.get('status')} message={body.get('message')}")
        return body["data"]

    def list_rules(self, alio_name: str, apba_id: str) -> Iterator[ListRow]:
        page = 1
        while True:
            data = self._json("/occasional/findRuleList.json",
                              {"type": "apbaNa", "word": alio_name, "pageNo": page})
            for r in data["result"]:
                if r.get("apbaId") != apba_id:
                    continue
                yield ListRow(str(r["seq"]), r["title"].strip(), r["apbaId"], r.get("insdRuleDivis"),
                              f"{r.get('submissionNo')}|{r.get('ruleStDa')}")
            if page >= int(data["page"]["totalPage"]):
                return
            page += 1

    def detail(self, seq: str) -> RuleDetail:
        d = self._json("/occasional/findRuleDtl.json", {"seq": seq})
        return RuleDetail(seq, d["title"].strip(), d.get("insdRuleDivis"), _date(d.get("retryRvsnYmd")),
                          _date(d.get("idate")), parse_bfiles(d.get("bFiles")), d)

    def download(self, file_no: str) -> bytes:
        return self.http.get(self.base + "/download/rulefiledown.json", params={"fileNo": file_no}).content
```

- [ ] **Step 5: 테스트 통과 확인 후 커밋**

Run: `uv run pytest tests/test_sniff_archive.py tests/test_alio.py -v` → 6 PASS

```bash
git add src/reg/collect/sniff.py src/reg/collect/archive.py src/reg/outbox.py src/reg/collect/alio.py tests/fixtures/alio_*.json tests/test_sniff_archive.py tests/test_alio.py
git commit -m "feat(collect): file sniffing, content-addressed archive, outbox, ALIO client"
```

---

### Task 6: 기관 설정과 ALIO 동기화

**Files:**
- Create: `config/institutions.yaml`, `src/reg/collect/alio_sync.py`, `tests/test_alio_sync.py`

**Interfaces:**
- Consumes: `AlioClient`, `store`, `sniff`, `outbox.write`, `runs.*`
- Produces:
  - `load_institutions(conn, path: Path) -> list[dict]`: YAML을 `institution` 테이블에 upsert하고, `active` 행을 돌려준다.
  - `sync_institution(conn, alio: AlioClient, blob: BlobStore, inst: dict, limit: int | None = None) -> dict`
    - 통계를 돌려준다: `{"rules_seen", "details_fetched", "files_fetched", "files_new_content", "files_rejected"}`
    - 규정마다 커밋한다.
    - `StopCollecting`·`AlioError`는 위로 전파한다.
  - outbox 페이로드 `regulation.source_fetched`: `{"source": "alio", "source_document_id", "institution_code", "seq", "file_no", "file_name"}`

**변경 감지 규칙:**
- 아래 셋 중 하나에 해당하면 상세를 조회한다.
  - 처음 보는 `seq`
  - `list_fingerprint`가 바뀜
  - 아직 받지 못한 파일이 있음
- 그 밖의 규정은 `last_seen_at`만 갱신한다.

**파일 처리 규칙:**
- 상세의 `files` 중 `alio_rule_file`에 없는 `fileNo`만 내려받는다.
- 내려받은 파일 처리:
  - `sniff`가 None이면 → `status='rejected'`로 기록하고 이벤트를 내지 않는다.
  - `store().is_new`면 → `regulation.source_fetched`를 기록한다.
  - 내용이 이미 있던 것이면 → 매핑만 기록한다.

- [ ] **Step 1: 기관 설정 작성** (ALIO `apbaId`는 2026-10-02 확인값)

```yaml
# config/institutions.yaml
# M2 파일럿 4개 기관. 나머지 출연연은 M6에서 추가 (ALIO 기관명·apbaId 확인 후)
- {code: NST,  name: 국가과학기술연구회, kind: NST, alio_apba_id: C0909, alio_name: 국가과학기술연구회}
- {code: KASI, name: 한국천문연구원,     kind: GRI, alio_apba_id: C0266, alio_name: 한국천문연구원}
- {code: KIST, name: 한국과학기술연구원, kind: GRI, alio_apba_id: C0159, alio_name: 한국과학기술연구원}
- {code: ETRI, name: 한국전자통신연구원, kind: GRI, alio_apba_id: C0251, alio_name: 한국전자통신연구원}
```

- [ ] **Step 2: 실패하는 테스트 작성**

```python
# tests/test_alio_sync.py
import json
from pathlib import Path

import pytest
import respx

from reg.collect.alio import AlioClient
from reg.collect.alio_sync import load_institutions, sync_institution
from reg.collect.polite import PoliteClient, StopCollecting
from reg.storage.blob import LocalBlobStore

FX = Path(__file__).parent / "fixtures"
BASE = "https://www.alio.go.kr"
PDF_A, PDF_B = b"%PDF-1.4 A", b"%PDF-1.4 B"


def setup_inst(conn, tmp_path):
    cfg = tmp_path / "i.yaml"
    cfg.write_text("- {code: KASI, name: 한국천문연구원, kind: GRI, alio_apba_id: C0266, alio_name: 한국천문연구원}\n")
    return load_institutions(conn, cfg)[0]


def mock_alio(files_by_no: dict[str, bytes], bfiles: str):
    lst = json.loads((FX / "alio_list_kasi_p1.json").read_text())
    lst["data"]["result"] = lst["data"]["result"][:1]  # seq 47852 하나만
    det = json.loads((FX / "alio_detail.json").read_text())
    det["data"]["bFiles"] = bfiles
    respx.get(f"{BASE}/occasional/findRuleList.json").respond(200, json=lst)
    respx.get(f"{BASE}/occasional/findRuleDtl.json").respond(200, json=det)
    dl = respx.get(f"{BASE}/download/rulefiledown.json")
    dl.side_effect = lambda req: __import__("httpx").Response(200, content=files_by_no[req.url.params["fileNo"]])
    return dl


def run(conn, tmp_path, inst):
    alio = AlioClient(PoliteClient("alio", 0, sleep=lambda s: None))
    return sync_institution(conn, alio, LocalBlobStore(tmp_path / "blob"), inst)


def events(conn):
    return conn.execute("SELECT payload FROM regulation.outbox WHERE topic='regulation.source_fetched'"
                        " ORDER BY id").fetchall()


@respx.mock
def test_first_run_fetches_all_and_emits(conn, tmp_path):
    inst = setup_inst(conn, tmp_path)
    mock_alio({"1": PDF_A, "2": PDF_B}, "1|a.pdf,2|b.pdf")
    st = run(conn, tmp_path, inst)
    assert st["files_fetched"] == 2 and st["files_new_content"] == 2
    assert [e["payload"]["file_no"] for e in events(conn)] == ["1", "2"]
    rule = conn.execute("SELECT * FROM regulation.alio_rule WHERE seq='47852'").fetchone()
    assert str(rule["revised_on"]) == "2024-01-17"


@respx.mock
def test_second_run_is_noop(conn, tmp_path):
    inst = setup_inst(conn, tmp_path)
    dl = mock_alio({"1": PDF_A}, "1|a.pdf")
    run(conn, tmp_path, inst)
    calls = dl.call_count
    st = run(conn, tmp_path, inst)
    assert st["details_fetched"] == 0 and dl.call_count == calls and len(events(conn)) == 1


@respx.mock
def test_new_file_no_with_same_content_records_mapping_without_event(conn, tmp_path):
    inst = setup_inst(conn, tmp_path)
    mock_alio({"1": PDF_A}, "1|a.pdf")
    run(conn, tmp_path, inst)
    respx.reset()
    mock_alio({"1": PDF_A, "9": PDF_A}, "1|a.pdf,9|a-재게시.pdf")
    conn.execute("UPDATE regulation.alio_rule SET list_fingerprint='old'")
    conn.commit()
    st = run(conn, tmp_path, inst)
    assert st["files_fetched"] == 1 and st["files_new_content"] == 0 and len(events(conn)) == 1
    n = conn.execute("SELECT count(*) AS n FROM regulation.alio_rule_file").fetchone()["n"]
    assert n == 2


@respx.mock
def test_html_instead_of_file_is_rejected(conn, tmp_path):
    inst = setup_inst(conn, tmp_path)
    mock_alio({"1": b"<html>error</html>"}, "1|a.pdf")
    st = run(conn, tmp_path, inst)
    f = conn.execute("SELECT * FROM regulation.alio_rule_file WHERE file_no='1'").fetchone()
    assert st["files_rejected"] == 1 and f["status"] == "rejected" and f["source_document_id"] is None
    assert events(conn) == []


@respx.mock
def test_stop_midway_then_resume(conn, tmp_path):
    inst = setup_inst(conn, tmp_path)
    mock_alio({"1": PDF_A, "2": PDF_B}, "1|a.pdf,2|b.pdf")
    respx.get(f"{BASE}/download/rulefiledown.json", params={"fileNo": "2"}).respond(403)
    with pytest.raises(StopCollecting):
        run(conn, tmp_path, inst)
    conn.rollback()
    assert conn.execute("SELECT count(*) AS n FROM regulation.alio_rule_file").fetchone()["n"] == 0
    respx.reset()
    mock_alio({"1": PDF_A, "2": PDF_B}, "1|a.pdf,2|b.pdf")
    st = run(conn, tmp_path, inst)
    assert st["files_fetched"] == 2
```

- [ ] **Step 3: 테스트가 실패하는지 확인**

Run: `uv run pytest tests/test_alio_sync.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 4: 구현**

```python
# src/reg/collect/alio_sync.py
import json
from pathlib import Path

import yaml

from reg import outbox
from reg.collect.alio import AlioClient, RuleDetail
from reg.collect.archive import store
from reg.collect.sniff import sniff
from reg.storage.blob import BlobStore

DOWNLOAD_URL = "https://www.alio.go.kr/download/rulefiledown.json?fileNo={}"


def load_institutions(conn, path: Path) -> list[dict]:
    for i in yaml.safe_load(Path(path).read_text(encoding="utf-8")):
        conn.execute(
            "INSERT INTO regulation.institution (code, name, kind, alio_apba_id, alio_name)"
            " VALUES (%(code)s, %(name)s, %(kind)s, %(alio_apba_id)s, %(alio_name)s)"
            " ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, kind = EXCLUDED.kind,"
            " alio_apba_id = EXCLUDED.alio_apba_id, alio_name = EXCLUDED.alio_name", i)
    conn.commit()
    return conn.execute("SELECT * FROM regulation.institution WHERE active ORDER BY id").fetchall()


def _upsert_rule(conn, inst_id: int, d: RuleDetail, fingerprint: str) -> None:
    conn.execute(
        "INSERT INTO regulation.alio_rule (seq, institution_id, title, divis, revised_on, posted_on,"
        " list_fingerprint, detail) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)"
        " ON CONFLICT (seq) DO UPDATE SET title = EXCLUDED.title, divis = EXCLUDED.divis,"
        " revised_on = EXCLUDED.revised_on, posted_on = EXCLUDED.posted_on,"
        " list_fingerprint = EXCLUDED.list_fingerprint, detail = EXCLUDED.detail, last_seen_at = now()",
        (d.seq, inst_id, d.title, d.divis, d.revised_on, d.posted_on, fingerprint,
         json.dumps(d.raw, ensure_ascii=False)))


def sync_institution(conn, alio: AlioClient, blob: BlobStore, inst: dict, limit: int | None = None) -> dict:
    st = dict(rules_seen=0, details_fetched=0, files_fetched=0, files_new_content=0, files_rejected=0)
    for row in alio.list_rules(inst["alio_name"], inst["alio_apba_id"]):
        if limit is not None and st["rules_seen"] >= limit:
            break
        st["rules_seen"] += 1
        known = conn.execute(
            "SELECT r.list_fingerprint, (SELECT count(*) FROM regulation.alio_rule_file f WHERE f.seq = r.seq) AS nfiles"
            " FROM regulation.alio_rule r WHERE r.seq = %s", (row.seq,)).fetchone()
        if known and known["list_fingerprint"] == row.fingerprint and known["nfiles"] > 0:
            conn.execute("UPDATE regulation.alio_rule SET last_seen_at = now() WHERE seq = %s", (row.seq,))
            conn.commit()
            continue
        d = alio.detail(row.seq)
        st["details_fetched"] += 1
        _upsert_rule(conn, inst["id"], d, row.fingerprint)
        have = {r["file_no"] for r in conn.execute(
            "SELECT file_no FROM regulation.alio_rule_file WHERE seq = %s", (row.seq,)).fetchall()}
        for ord_, (file_no, name) in enumerate(d.files):
            if file_no in have:
                continue
            content = alio.download(file_no)
            st["files_fetched"] += 1
            kind = sniff(content, name)
            if kind is None:
                st["files_rejected"] += 1
                conn.execute("INSERT INTO regulation.alio_rule_file (file_no, seq, file_name, ord, status,"
                             " reject_reason) VALUES (%s,%s,%s,%s,'rejected',%s)",
                             (file_no, row.seq, name, ord_, f"형식 불명 ({content[:16]!r})"))
                continue
            doc = store(conn, blob, source="alio", url=DOWNLOAD_URL.format(file_no), content=content,
                        kind=kind, meta={"seq": row.seq, "file_no": file_no, "file_name": name,
                                         "institution_code": inst["code"]})
            conn.execute("INSERT INTO regulation.alio_rule_file (file_no, seq, file_name, ord, status,"
                         " source_document_id) VALUES (%s,%s,%s,%s,'fetched',%s)",
                         (file_no, row.seq, name, ord_, doc.id))
            if doc.is_new:
                st["files_new_content"] += 1
                outbox.write(conn, "regulation.source_fetched", {
                    "source": "alio", "source_document_id": doc.id, "institution_code": inst["code"],
                    "seq": row.seq, "file_no": file_no, "file_name": name})
        conn.commit()  # 규정 단위 커밋: 중간에 멈춰도 다시 실행하면 이어서 받는다
    return st
```

- [ ] **Step 5: 테스트 통과 확인 후 커밋**

Run: `uv run pytest tests/test_alio_sync.py -v` → 5 PASS

```bash
git add config/institutions.yaml src/reg/collect/alio_sync.py tests/test_alio_sync.py
git commit -m "feat(collect): ALIO institution sync with change detection and outbox events"
```

---

### Task 7: law.go.kr 클라이언트와 핵심 법령 동기화

**Files:**
- Create: `config/laws.yaml`, `src/reg/collect/lawgo.py`, `src/reg/collect/law_sync.py`, `tests/fixtures/lawgo_search.xml`, `tests/fixtures/lawgo_service_283849.xml`, `tests/test_lawgo.py`

**Interfaces:**
- Produces:
  - `lawgo.norm_name(s: str) -> str`: 공백과 가운뎃점 변형(`·ㆍ‧∙`)을 없앤다.
  - `lawgo.LawSummary(mst, law_id, name, kind, promulgated_on: date, effective_on: date, status)` (dataclass)
  - `lawgo.parse_search(xml: bytes) -> list[LawSummary]`
  - `lawgo.LawGoClient(http: PoliteClient, oc: str, base: str = "https://www.law.go.kr")`
    - `.search(query: str) -> list[LawSummary]`
    - `.fetch(mst: str) -> bytes`
  - `law_sync.sync_laws(conn, client: LawGoClient, blob: BlobStore, names: list[str]) -> dict`
    - 통계: `{"checked", "fetched", "not_found": [names]}`
  - outbox 페이로드 `regulation.law_fetched`: `{"law_id", "mst", "name", "source_document_id"}`

**규칙:**
- 이름마다 검색해서, `norm_name`이 같고 `status == "현행"`인 결과를 고른다.
- `law_watch.last_mst`와 MST가 다를 때만 본문을 받아 저장하고 이벤트를 낸다.
- 법령 XML의 `FileKind`는 `("application/xml", "xml")`로 고정한다.

- [ ] **Step 1: 픽스처 기록과 시드 작성**

```bash
uv run python - <<'EOF'
import httpx
H = {"User-Agent": "NST-Regulation-Collector/0.1 (+contact: bigdatanigel1513@gmail.com)"}
B = "https://www.law.go.kr/DRF"
open("tests/fixtures/lawgo_search.xml", "wb").write(httpx.get(f"{B}/lawSearch.do", headers=H, params={
    "OC": "test", "target": "law", "type": "XML", "display": 100, "query": "국가연구개발혁신법"}).content)
open("tests/fixtures/lawgo_service_283849.xml", "wb").write(httpx.get(f"{B}/lawService.do", headers=H, params={
    "OC": "test", "target": "law", "MST": "283849", "type": "XML"}).content)
EOF
```

기록된 내용 중 테스트가 기대하는 값(2026-10-02 기록)은 다음과 같다. 검색 결과는 3건이다.

| MST | 법령ID | 이름 | 구분 | 공포일 | 시행일 |
|---|---|---|---|---|---|
| 283849 | 013774 | 국가연구개발혁신법 | 법률 | 20260310 | 20260911 |
| 288335 | 013933 | 국가연구개발혁신법 시행령 | 대통령령 | 20260728 | 20260911 |
| 289003 | 013980 | 국가연구개발혁신법 시행규칙 | 과학기술정보통신부령 | 20260820 | 20260820 |

```yaml
# config/laws.yaml  — 연구행정 핵심 법령 시드 (spec D-07). 이름은 law.go.kr 표기와 정규화 비교
- 국가연구개발혁신법
- 국가연구개발혁신법 시행령
- 국가연구개발혁신법 시행규칙
- 과학기술분야 정부출연연구기관 등의 설립·운영 및 육성에 관한 법률
- 과학기술분야 정부출연연구기관 등의 설립·운영 및 육성에 관한 법률 시행령
- 공공기관의 운영에 관한 법률
- 공공기관의 운영에 관한 법률 시행령
- 국가를 당사자로 하는 계약에 관한 법률
- 국가를 당사자로 하는 계약에 관한 법률 시행령
- 공무원 여비 규정
```

- [ ] **Step 2: 실패하는 테스트 작성**

```python
# tests/test_lawgo.py
from datetime import date
from pathlib import Path

import respx

from reg.collect.law_sync import sync_laws
from reg.collect.lawgo import LawGoClient, norm_name, parse_search
from reg.collect.polite import PoliteClient
from reg.storage.blob import LocalBlobStore

FX = Path(__file__).parent / "fixtures"
B = "https://www.law.go.kr/DRF"


def test_norm_name_ignores_spaces_and_middle_dots():
    assert norm_name("설립·운영 및 육성") == norm_name("설립ㆍ운영 및육성")


def test_parse_search():
    rows = parse_search((FX / "lawgo_search.xml").read_bytes())
    assert [r.mst for r in rows] == ["283849", "288335", "289003"]
    r = rows[0]
    assert (r.law_id, r.name, r.kind, r.status) == ("013774", "국가연구개발혁신법", "법률", "현행")
    assert r.promulgated_on == date(2026, 3, 10) and r.effective_on == date(2026, 9, 11)


@respx.mock
def test_sync_fetches_once_then_skips_until_mst_changes(conn, tmp_path):
    respx.get(f"{B}/lawSearch.do").respond(200, content=(FX / "lawgo_search.xml").read_bytes())
    svc = respx.get(f"{B}/lawService.do").respond(200, content=(FX / "lawgo_service_283849.xml").read_bytes())
    client = LawGoClient(PoliteClient("lawgo", 0, sleep=lambda s: None), oc="test")
    blob = LocalBlobStore(tmp_path)
    st = sync_laws(conn, client, blob, ["국가연구개발혁신법", "없는 법"])
    assert st["fetched"] == 1 and st["not_found"] == ["없는 법"] and svc.call_count == 1
    ev = conn.execute("SELECT payload FROM regulation.outbox WHERE topic='regulation.law_fetched'").fetchall()
    assert ev[0]["payload"]["mst"] == "283849"
    st2 = sync_laws(conn, client, blob, ["국가연구개발혁신법"])
    assert st2["fetched"] == 0 and svc.call_count == 1
    w = conn.execute("SELECT * FROM regulation.law_watch WHERE law_id='013774'").fetchone()
    assert w["last_mst"] == "283849" and str(w["effective_on"]) == "2026-09-11"
```

- [ ] **Step 3: 테스트가 실패하는지 확인**

Run: `uv run pytest tests/test_lawgo.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 4: 구현**

```python
# src/reg/collect/lawgo.py
"""국가법령정보 공동활용 Open API (DRF) 클라이언트."""
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date

from reg.collect.polite import PoliteClient

_DOTS = re.compile(r"[\s·ㆍ‧∙・]")


def norm_name(s: str) -> str:
    return _DOTS.sub("", s or "")


def _ymd(s: str | None) -> date | None:
    return date(int(s[:4]), int(s[4:6]), int(s[6:8])) if s and len(s) == 8 and s.isdigit() else None


@dataclass
class LawSummary:
    mst: str
    law_id: str
    name: str
    kind: str
    promulgated_on: date | None
    effective_on: date | None
    status: str


def parse_search(xml: bytes) -> list[LawSummary]:
    root = ET.fromstring(xml)
    return [LawSummary(e.findtext("법령일련번호", "").strip(), e.findtext("법령ID", "").strip(),
                       (e.findtext("법령명한글") or "").strip(), (e.findtext("법령구분명") or "").strip(),
                       _ymd(e.findtext("공포일자")), _ymd(e.findtext("시행일자")),
                       (e.findtext("현행연혁코드") or "").strip())
            for e in root.findall("law")]


class LawGoClient:
    def __init__(self, http: PoliteClient, oc: str, base: str = "https://www.law.go.kr"):
        self.http, self.oc, self.base = http, oc, base

    def search(self, query: str) -> list[LawSummary]:
        r = self.http.get(f"{self.base}/DRF/lawSearch.do", params={
            "OC": self.oc, "target": "law", "type": "XML", "display": 100, "query": query})
        return parse_search(r.content)

    def fetch(self, mst: str) -> bytes:
        return self.http.get(f"{self.base}/DRF/lawService.do", params={
            "OC": self.oc, "target": "law", "MST": mst, "type": "XML"}).content
```

```python
# src/reg/collect/law_sync.py
from reg import outbox
from reg.collect.archive import store
from reg.collect.lawgo import LawGoClient, norm_name
from reg.collect.sniff import FileKind
from reg.storage.blob import BlobStore

XML = FileKind("application/xml", "xml")
SERVICE_URL = "https://www.law.go.kr/DRF/lawService.do?target=law&type=XML&MST={}"


def sync_laws(conn, client: LawGoClient, blob: BlobStore, names: list[str]) -> dict:
    st = {"checked": 0, "fetched": 0, "not_found": []}
    for name in names:
        st["checked"] += 1
        hit = next((r for r in client.search(name)
                    if norm_name(r.name) == norm_name(name) and r.status == "현행"), None)
        if hit is None:
            st["not_found"].append(name)
            continue
        w = conn.execute("SELECT last_mst FROM regulation.law_watch WHERE law_id = %s", (hit.law_id,)).fetchone()
        if w and w["last_mst"] == hit.mst:
            conn.execute("UPDATE regulation.law_watch SET last_checked_at = now() WHERE law_id = %s", (hit.law_id,))
            conn.commit()
            continue
        doc = store(conn, blob, source="lawgo", url=SERVICE_URL.format(hit.mst), content=client.fetch(hit.mst),
                    kind=XML, meta={"law_id": hit.law_id, "mst": hit.mst, "name": hit.name})
        conn.execute(
            "INSERT INTO regulation.law_watch (law_id, name, kind, last_mst, promulgated_on, effective_on,"
            " source_document_id, last_checked_at) VALUES (%s,%s,%s,%s,%s,%s,%s, now())"
            " ON CONFLICT (law_id) DO UPDATE SET name = EXCLUDED.name, kind = EXCLUDED.kind,"
            " last_mst = EXCLUDED.last_mst, promulgated_on = EXCLUDED.promulgated_on,"
            " effective_on = EXCLUDED.effective_on, source_document_id = EXCLUDED.source_document_id,"
            " last_checked_at = now()",
            (hit.law_id, hit.name, hit.kind, hit.mst, hit.promulgated_on, hit.effective_on, doc.id))
        if doc.is_new:
            outbox.write(conn, "regulation.law_fetched",
                         {"law_id": hit.law_id, "mst": hit.mst, "name": hit.name, "source_document_id": doc.id})
        st["fetched"] += 1
        conn.commit()
    return st
```

- [ ] **Step 5: 테스트 통과 확인 후 커밋**

Run: `uv run pytest tests/test_lawgo.py -v` → 3 PASS

```bash
git add config/laws.yaml src/reg/collect/lawgo.py src/reg/collect/law_sync.py tests/fixtures/lawgo_* tests/test_lawgo.py
git commit -m "feat(collect): law.go.kr client and seed law sync"
```

---

### Task 8: CLI와 공유 인프라 실연결

**Files:**
- Create: `src/reg/cli.py`, `tests/test_cli_smoke.py`
- Modify: `README.md` (실행 방법 절 추가)

**Interfaces:**
- Consumes: 모든 이전 Task
- Produces (CLI):
  - `reg db bootstrap`: 슈퍼유저 DSN은 `--superuser-dsn` 또는 환경변수 `REG_SUPERUSER_URL`로 받는다. 비밀번호는 `REG_DATABASE_URL`, `REG_MIGRATOR_URL`에서 읽는다.
  - `reg db upgrade`
  - `reg bucket ensure`
  - `reg collect alio [--institution CODE] [--limit N]`
  - `reg collect law`
  - 각 collect 명령은 다음을 지킨다.
    - `fetch_run`을 시작하고, `request_log`를 기록하고, 끝나면 `finish_run`을 호출한다.
    - 예외가 나면 `failed`로 기록한 뒤 종료 코드 1로 끝낸다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_cli_smoke.py
from typer.testing import CliRunner

from reg.cli import app


def test_help_lists_commands():
    out = CliRunner().invoke(app, ["--help"]).output
    for cmd in ("db", "bucket", "collect"):
        assert cmd in out


def test_collect_help():
    out = CliRunner().invoke(app, ["collect", "--help"]).output
    assert "alio" in out and "law" in out
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `uv run pytest tests/test_cli_smoke.py -v`
Expected: FAIL (`ModuleNotFoundError: reg.cli`)

- [ ] **Step 3: 구현**

```python
# src/reg/cli.py
import os
from pathlib import Path
from urllib.parse import urlparse

import typer
import yaml

from reg.collect.alio import AlioClient
from reg.collect.alio_sync import load_institutions, sync_institution
from reg.collect.law_sync import sync_laws
from reg.collect.lawgo import LawGoClient
from reg.collect.polite import PoliteClient
from reg.collect.runs import db_logger, finish_run, start_run
from reg.db.bootstrap import bootstrap
from reg.db.conn import connect
from reg.db.migrate import upgrade
from reg.settings import get_settings
from reg.storage.blob import S3BlobStore

ROOT = Path(__file__).resolve().parents[2]
app = typer.Typer(no_args_is_help=True)
db = typer.Typer(no_args_is_help=True, help="DB 역할·스키마·마이그레이션")
bucket = typer.Typer(no_args_is_help=True, help="원본 보관 버킷")
collect = typer.Typer(no_args_is_help=True, help="ALIO·law.go.kr 수집")
app.add_typer(db, name="db")
app.add_typer(bucket, name="bucket")
app.add_typer(collect, name="collect")


def _blob() -> S3BlobStore:
    s = get_settings()
    return S3BlobStore(s.s3_endpoint, s.s3_bucket, s.s3_access_key, s.s3_secret_key)


@db.command("bootstrap")
def db_bootstrap(superuser_dsn: str = typer.Option(None, envvar="REG_SUPERUSER_URL")) -> None:
    s = get_settings()
    app_url, mig_url = urlparse(s.database_url), urlparse(s.migrator_url)
    bootstrap(superuser_dsn, app_url.path.lstrip("/"), mig_url.password, app_url.password)
    typer.echo("bootstrap 완료: reg_migrator, reg_app, schema regulation")


@db.command("upgrade")
def db_upgrade() -> None:
    upgrade(get_settings().migrator_url)
    typer.echo("migrate 완료")


@bucket.command("ensure")
def bucket_ensure() -> None:
    _blob().ensure_bucket()
    typer.echo(f"bucket 준비: {get_settings().s3_bucket}")


def _run(source: str, scope: str | None, body) -> None:
    conn = connect(get_settings().database_url)
    run_id = start_run(conn, source, scope)
    try:
        stats = body(conn, db_logger(conn, run_id))
    except Exception as e:
        finish_run(conn, run_id, "failed", {}, f"{type(e).__name__}: {e}")
        typer.echo(f"실패 (run {run_id}): {e}", err=True)
        raise typer.Exit(1)
    finish_run(conn, run_id, "succeeded", stats)
    typer.echo(f"완료 (run {run_id}): {stats}")


@collect.command("alio")
def collect_alio(institution: str = typer.Option(None, help="기관 코드 (예: KASI)"),
                 limit: int = typer.Option(None, help="기관당 규정 수 상한 (시험용)")) -> None:
    def body(conn, log):
        http = PoliteClient("alio", get_settings().alio_min_interval, log=log)
        alio, blob, total = AlioClient(http), _blob(), {}
        for inst in load_institutions(conn, ROOT / "config/institutions.yaml"):
            if institution and inst["code"] != institution:
                continue
            total[inst["code"]] = sync_institution(conn, alio, blob, inst, limit=limit)
        return total
    _run("alio", institution, body)


@collect.command("law")
def collect_law() -> None:
    def body(conn, log):
        s = get_settings()
        client = LawGoClient(PoliteClient("lawgo", s.lawgo_min_interval, log=log), oc=s.lawgo_oc)
        names = yaml.safe_load((ROOT / "config/laws.yaml").read_text(encoding="utf-8"))
        return sync_laws(conn, client, _blob(), names)
    _run("lawgo", None, body)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest -v` → 전체 PASS

- [ ] **Step 5: 공유 인프라에 실제로 연결**

1. `.env`를 만든다(커밋하지 않음).
   - 비밀번호는 새로 생성한다.
   - S3 키는 nst-nexus `.env`의 `STORAGE_NAIS_ACCESS_KEY`와 `STORAGE_NAIS_SECRET_KEY` 값을 쓴다.
   - `REG_LAWGO_OC`에는 개발 중에만 `test`를 쓴다. 운영 전에 기관 명의로 발급받은 키로 바꾼다.
2. 슈퍼유저 DSN은 다음과 같다. `postgresql://nais:<nst-nexus POSTGRES_PASSWORD>@127.0.0.1:21055/nais`

```bash
uv run reg db bootstrap
uv run reg db upgrade
uv run reg bucket ensure
uv run reg collect law
uv run reg collect alio --institution KASI --limit 3
```

Expected:
- `collect law`
  - `not_found`가 비어 있다.
  - 첫 실행에서 `fetched`는 10이다.
  - 다시 실행하면 `fetched`는 0이다.
- `collect alio --institution KASI --limit 3`
  - `rules_seen`은 3이다.
  - `files_fetched`는 1 이상이다.
  - 다시 실행하면 `details_fetched`는 0이다.
- DB 확인: `docker exec nais-postgres-1 psql -U nais -d nais -c "select count(*) from regulation.source_document"` 결과가 0보다 크다.

- [ ] **Step 6: integration 테스트 실행, README 갱신, 커밋**

Run: `uv run pytest -m integration -v` → S3 roundtrip PASS

README에 "실행" 절을 추가한다. 내용은 위 Step 5의 명령 5줄과 각각의 한 줄 설명이다.

```bash
git add src/reg/cli.py tests/test_cli_smoke.py README.md
git commit -m "feat(cli): db/bucket/collect commands wired to shared infra"
```

---

## Self-Review 결과

- **스펙 대응 (M1 범위: 13절 M1, 6.1, 4.1)**
  - 저장소: Task 1
  - 스키마: Task 2
  - polite client: Task 4
  - 원본 보관: Task 3, 5
  - ALIO 수집기: Task 5, 6
  - law.go.kr 수집기: Task 7
  - 실연결: Task 8
  - 6.1의 "과거 파일 전체 수집(초기 적재)"은 `bFiles` 전체 다운로드로 충족한다(Task 6).
  - 6.1의 "참조로 발견된 법령 자동 추가"는 참조 추출이 생기는 M2로 넘긴다.
- **outbox relay와 스케줄러**는 소비자가 생기는 M2에서 다룬다. M1은 이벤트 기록까지만 한다.
- **타입 일치 확인**
  - `FileKind`, `StoredDoc`, `ListRow.fingerprint`, `RuleDetail.files`의 이름과 타입이 Task 5·6·7 사이에서 서로 맞는다.
  - `sync_institution`이 돌려주는 통계 키가 테스트와 CLI에서 같다.
