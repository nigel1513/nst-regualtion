# M2a 구조화·버전 적재 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** M1이 보관한 원본을 조문 단위로 구조화해서 `regulation` 스키마에 버전과 함께 적재한다.

- 원본 종류: ALIO 내부규정(HWP/HWPX/PDF), law.go.kr 법령 XML
- 구조 단위: 장·조·항·호·목, 부칙, 별표 원문
- 버전 정보: 시행일 판정과 그 근거·상태, 조문 단위 변경 이력, 현행/과거/미래 상태

**Architecture:** 단계별로 서로 독립된 모듈로 나눈다.

1. **추출기** (`reg.extract.*`): 바이트를 `Block` 목록(텍스트, 쪽, bbox)으로 바꾼다.
2. **구조 파서** (`reg.structure.parse`): `Block` 목록을 `ParsedDoc`로 바꾼다.
3. **시행일 판정기** (`reg.structure.effective`): `ParsedDoc`와 출처 메타데이터로 시행일, 근거, 상태를 정한다.
4. **적재기** (`reg.load.loader`): work, work_version, provision 등을 기록하고 변경 이력을 다시 계산한다.
5. **처리기** (`reg.process`): outbox 이벤트를 하나씩 가져와 1~4를 호출한다. 이벤트마다 트랜잭션을 따로 쓰고, 실패하면 재시도 횟수를 센다.

law.go.kr XML은 2단계 대신 `reg.structure.law_xml`이 같은 `ParsedDoc`를 만든다.

**Tech Stack:** M1 스택에 pdfplumber(PDF 줄과 좌표 추출), olefile(HWP 5.0 OLE)을 더한다.

**Spec:** `docs/superpowers/specs/2026-10-01-regulation-platform-design.md` (5.1~5.3, 6.2, 6.3, 6.5, 6.6)

## Global Constraints

- **DB와 실행 환경**: M1 Global Constraints를 그대로 따른다. 모든 테이블은 `regulation.` 스키마에 두고, 앱 DML은 `reg_app` 역할로 한다. 실행은 `uv run`, 테스트는 `uv run pytest`로 한다.
- **식별자 (spec 5.2)**
  - 법령: `kr/law/{법령ID}`
  - 내부규정: `kr/reg/{기관코드}/{정규화 규정명}`
    - 같은 ALIO `seq`는 항상 같은 work로 간다. `seq`는 `work.external_ids.alio_seq`에 둔다.
    - 이름이 다른 `seq`와 겹치면 `~{seq}`를 붙인다.
  - 버전: `{work}@{YYYY-MM-DD}`. 같은 날짜가 겹치면 `.2`, `.3`을 붙인다. 시행일을 모르면 `{work}@undated-{source_document_id}`.
- **조항 경로**: `article` 단위 아래에서만 `.`로 이어 붙인다.

  | 단위 | 경로 |
  |---|---|
  | 장 | `c{n}` |
  | 절 | `c{n}-s{m}` |
  | 조 | `a{n}` 또는 `a{n}-{k}` (제n조의k) |
  | 항 | `{조}.p{n}` |
  | 호 | `{조 또는 항}.i{n}` (n은 정수, 가지호 `{n}-{k}`) |
  | 목 | `{호}.s{가}` |
  | 부칙 | `supp@{YYYY-MM-DD}`. 날짜 중복이면 `~2`, 날짜가 없으면 `supp#{n}` |
  | 부칙 조문 | `{부칙}/a{n}` |
  | 별표 | `annex{n}` (`n`은 `별표 제n호`의 n, 가지번호는 `{n}-{k}`) |
  | 별지 서식 | `form{n}` |

- **시행일 판정 우선순위 (spec 6.5)**: 부칙 시행 조항 > 문서 안 개정 이력표의 마지막 날짜 > ALIO 개정일(그 규정의 최신 파일에만 적용) > 파일명 날짜
  - `effective_basis` ∈ `api|supplement|history|alio|filename|none`
  - `effective_status` ∈ `CONFIRMED|UNCERTAIN|CONFLICT`
- **version_state**는 기준일 = 오늘(KST)로 정한다.
  - 시행일이 미래면 `FUTURE`
  - 시행일이 오늘 이전인 버전 중 가장 늦은 것이 `CURRENT`
  - 나머지는 `HISTORICAL`
  - 시행일이 없으면 `UNDATED`
- **변경 종류 (spec 6.6)**: `ADDED|MODIFIED|DELETED|RENUMBERED|ANNOTATION_ONLY`. 실질 변경은 `ANNOTATION_ONLY`를 뺀 나머지다.
- **outbox 처리**
  - `processed_at IS NULL AND attempts < 3`인 이벤트를 `FOR UPDATE SKIP LOCKED`로 가져온다.
  - 성공하면 `processed_at`을 기록한다.
  - 실패하면 `attempts`를 1 늘리고 `last_error`를 남긴다. 3회 실패하면 보류(parked)된다.

## Review Focus

1. **PDF 목차·머리글·쪽번호가 본문으로 섞이는 경우.** 목차의 "제 1 장 총 칙"이 본문 장으로 잡혀 본문 장이 무시되면 안 된다. Task 3에서 천문연 실파일로 테스트한다.
2. **줄 첫머리의 "제13조의 근무지내 출장…" 같은 참조가 새 조문으로 오인되는 경우.** 조문 제목 괄호나 "삭제"가 없고, 조 번호가 뒤로 가면 조문으로 보지 않는다. Task 3에서 테스트한다.
3. **부칙 안의 "제1조(시행일)"가 본문 제1조를 덮어쓰는 경우.** 부칙 조문은 `supp…/a1` 경로로만 들어가야 한다. Task 3에서 천문연과 NST 실파일로 테스트한다.
4. **같은 날짜의 부칙이 두 번 나오는 경우**(NST에 실제로 있음). 경로가 겹치지 않아야 한다(`~2`). Task 3에서 테스트한다.
5. **버전이 시행일 순서와 다르게 도착하는 경우**(과거 파일이 나중에 처리됨). 변경 이력과 `effective_to`가 시행일 순서로 다시 계산되어야 한다. Task 6에서 테스트한다.

---

## File Structure

```
src/reg/
├── structure/
│   ├── __init__.py
│   ├── model.py        # Block, Prov, HistEntry, ParsedDoc, to_json/from_json
│   ├── text.py         # clean, Joiner(어절 사전 기반 줄 잇기), split_notes, parse_dot_date, KO/DOT 날짜
│   ├── parse.py        # parse_blocks(blocks) -> ParsedDoc  (내부규정 공통 파서)
│   ├── law_xml.py      # parse_law_xml(bytes) -> ParsedDoc
│   └── effective.py    # resolve(doc, alio_date, filename) -> Effective
├── extract/
│   ├── __init__.py     # extract(data, mime, filename) -> list[Block]
│   ├── hwp.py          # extract_hwp
│   ├── hwpx.py         # extract_hwpx
│   └── pdf.py          # extract_pdf
├── load/
│   ├── __init__.py
│   └── loader.py       # upsert_work, add_version, rebuild_work
├── process.py          # process_once(conn, blob, limit) -> dict, handlers
└── migrations/versions/0002_structure.py
tests/
├── fixtures/samples/   # kasi-yeobi-339.pdf, nst-yeobi-18.hwp (data/samples 복사)
├── test_text.py
├── test_extract.py
├── test_parse.py
├── test_law_xml.py
├── test_effective.py
├── test_loader.py
└── test_process.py
```

---

### Task 1: 0002 마이그레이션 (구조화 테이블)

**Files:**
- Create: `src/reg/migrations/versions/0002_structure.py`, `tests/test_migrations_0002.py`
- Modify: `tests/conftest.py`의 TRUNCATE 목록에 새 테이블을 추가

**Interfaces:**
- Produces: 테이블 `work`, `work_version`, `amendment_history`, `provision`, `provision_version`, `version_provision`, `provision_change`, 컬럼 `outbox.last_error`

- [ ] **Step 1: 실패하는 테스트**

```python
# tests/test_migrations_0002.py
NEW = {"work", "work_version", "amendment_history", "provision", "provision_version",
       "version_provision", "provision_change"}


def test_structure_tables_exist(conn):
    rows = conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='regulation'").fetchall()
    assert NEW <= {r["table_name"] for r in rows}
    cols = conn.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='regulation'"
                        " AND table_name='outbox'").fetchall()
    assert "last_error" in {c["column_name"] for c in cols}
```

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_migrations_0002.py -q` → FAIL (`assert NEW <= …`)

- [ ] **Step 3: 마이그레이션과 conftest TRUNCATE 갱신**

```python
# src/reg/migrations/versions/0002_structure.py
"""M2a 구조화·버전 테이블"""
from alembic import op

revision = "0002"
down_revision = "0001"

DDL = """
ALTER TABLE regulation.outbox ADD COLUMN last_error text;
CREATE TABLE regulation.work (
  id text PRIMARY KEY,
  kind text NOT NULL,
  institution_id int REFERENCES regulation.institution(id),
  title text NOT NULL,
  external_ids jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX work_alio_seq ON regulation.work ((external_ids->>'alio_seq')) WHERE external_ids ? 'alio_seq';
CREATE TABLE regulation.work_version (
  id text PRIMARY KEY,
  work_id text NOT NULL REFERENCES regulation.work(id),
  source_document_id bigint NOT NULL REFERENCES regulation.source_document(id),
  title text NOT NULL,
  promulgated_on date,
  posted_on date,
  effective_from date,
  effective_to date,
  effective_basis text NOT NULL,
  effective_status text NOT NULL CHECK (effective_status IN ('CONFIRMED', 'UNCERTAIN', 'CONFLICT')),
  version_state text NOT NULL DEFAULT 'UNDATED'
    CHECK (version_state IN ('FUTURE', 'CURRENT', 'HISTORICAL', 'UNDATED')),
  amendment_kind text,
  amendment_no text,
  class_code text,
  parsed jsonb NOT NULL,
  parse_stats jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (work_id, source_document_id)
);
CREATE TABLE regulation.amendment_history (
  work_version_id text NOT NULL REFERENCES regulation.work_version(id) ON DELETE CASCADE,
  ord int NOT NULL,
  kind text NOT NULL,
  date date NOT NULL,
  number text,
  PRIMARY KEY (work_version_id, ord)
);
CREATE TABLE regulation.provision (
  id bigserial PRIMARY KEY,
  work_id text NOT NULL REFERENCES regulation.work(id),
  lineage_key text NOT NULL,
  UNIQUE (work_id, lineage_key)
);
CREATE TABLE regulation.provision_version (
  id bigserial PRIMARY KEY,
  provision_id bigint NOT NULL REFERENCES regulation.provision(id) ON DELETE CASCADE,
  path text NOT NULL,
  unit text NOT NULL,
  number_label text NOT NULL,
  heading text,
  parent_path text,
  text text NOT NULL,
  text_norm_hash text NOT NULL,
  annotations jsonb NOT NULL DEFAULT '[]',
  deleted boolean NOT NULL DEFAULT false,
  effective_from_override date,
  source_anchor jsonb,
  meta jsonb NOT NULL DEFAULT '{}'
);
CREATE TABLE regulation.version_provision (
  work_version_id text NOT NULL REFERENCES regulation.work_version(id) ON DELETE CASCADE,
  provision_version_id bigint NOT NULL REFERENCES regulation.provision_version(id) ON DELETE CASCADE,
  ord int NOT NULL,
  PRIMARY KEY (work_version_id, provision_version_id)
);
CREATE TABLE regulation.provision_change (
  id bigserial PRIMARY KEY,
  work_id text NOT NULL REFERENCES regulation.work(id),
  from_version_id text REFERENCES regulation.work_version(id) ON DELETE CASCADE,
  to_version_id text NOT NULL REFERENCES regulation.work_version(id) ON DELETE CASCADE,
  provision_id bigint NOT NULL REFERENCES regulation.provision(id) ON DELETE CASCADE,
  from_pv_id bigint REFERENCES regulation.provision_version(id) ON DELETE CASCADE,
  to_pv_id bigint REFERENCES regulation.provision_version(id) ON DELETE CASCADE,
  kind text NOT NULL CHECK (kind IN ('ADDED', 'MODIFIED', 'DELETED', 'RENUMBERED', 'ANNOTATION_ONLY'))
);
CREATE INDEX provision_change_to ON regulation.provision_change (to_version_id);
CREATE INDEX version_provision_pv ON regulation.version_provision (provision_version_id);
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    for t in ["provision_change", "version_provision", "provision_version", "provision", "amendment_history",
              "work_version", "work"]:
        op.execute(f"DROP TABLE regulation.{t}")
    op.execute("ALTER TABLE regulation.outbox DROP COLUMN last_error")
```

`tests/conftest.py`의 TRUNCATE 문 맨 앞에 다음을 추가한다. `regulation.provision_change, regulation.version_provision, regulation.provision_version, regulation.provision, regulation.amendment_history, regulation.work_version, regulation.work,`

- [ ] **Step 4: 통과 확인 후 커밋**

Run: `uv run pytest -q` → 전체 PASS

```bash
git add src/reg/migrations/versions/0002_structure.py tests/test_migrations_0002.py tests/conftest.py
git commit -m "feat(db): structure and version tables (0002)"
```

---

### Task 2: 모델과 텍스트 유틸리티

**Files:**
- Create: `src/reg/structure/__init__.py`, `src/reg/structure/model.py`, `src/reg/structure/text.py`, `tests/test_text.py`

**Interfaces:**
- Produces:
  - `Block(text: str, page: int | None = None, bbox: tuple | None = None)`
  - `Prov(path, unit, label, heading=None, text="", parent=None, annotations=[], deleted=False, effective_override: date | None = None, anchor: dict | None = None, meta: dict = {})`
  - `HistEntry(kind: str, date: date, number: str | None = None)`
  - `ParsedDoc(title, class_code, history: list[HistEntry], provisions: list[Prov], meta: dict = {})`
    - 메서드: `.get(path)`, `.children(path)`, `.supplements()`, `.to_json() -> dict`, `ParsedDoc.from_json(d)`
  - `text.clean(s) -> str`
  - `text.split_notes(s) -> tuple[str, list[str]]`
  - `text.parse_dot_date(s) -> date | None`: `'2024. 1. 17.'`, `'2023.12.21'`, `'20260911'`, `"'19.1.21."`(2자리 연도 → 19xx/20xx) 형식을 받는다.
  - `text.Joiner(lines: list[str])`, `.join(prev: str, nxt: str) -> str`

- [ ] **Step 1: 실패하는 테스트**

```python
# tests/test_text.py
from datetime import date

from reg.structure.model import HistEntry, ParsedDoc, Prov
from reg.structure.text import Joiner, clean, parse_dot_date, split_notes


def test_clean_strips_controls_and_spaces():
    assert clean("\x0b제1조　(목적)  이  규정") == "제1조 (목적) 이 규정"


def test_split_notes_extracts_amendment_annotations():
    text, notes = split_notes("증빙서를 제출하여야 한다. <개정 '19.1.21., 2020.11.6.> [본조신설 '07.12.28]")
    assert text == "증빙서를 제출하여야 한다."
    assert notes == ["<개정 '19.1.21., 2020.11.6.>", "[본조신설 '07.12.28]"]


def test_parse_dot_date_variants():
    assert parse_dot_date("2024. 1. 17.") == date(2024, 1, 17)
    assert parse_dot_date("<2023.12.21.>") == date(2023, 12, 21)
    assert parse_dot_date("20260911") == date(2026, 9, 11)
    assert parse_dot_date("'19.1.21.") == date(2019, 1, 21)
    assert parse_dot_date("없음") is None


def test_joiner_merges_mid_word_and_spaces_known_words():
    j = Joiner(["7일 이내에 출장을 확인할 수 있다", "실비로 지급한 여비 항목", "이 규정은"])
    assert j.join("7일 이내에 출", "장을 확인") == "7일 이내에 출장을 확인"   # '출'은 사전에 없음 → 붙임
    assert j.join("실비로 지급한", "여비 항목") == "실비로 지급한 여비 항목"   # '지급한'은 어절 → 띄움
    assert j.join("7일 이", "내에 출장") == "7일 이내에 출장"                  # 합친 '이내에'가 사전에 있음 → 붙임
    assert j.join("다음과 같다.", "1. 운임") == "다음과 같다. 1. 운임"


def test_parsed_doc_roundtrip():
    d = ParsedDoc("여비규정", "2120", [HistEntry("개정", date(2024, 1, 17), "339")],
                  [Prov("a1", "article", "제1조", "목적", "이 규정은", meta={"x": 1})], {"k": "v"})
    assert ParsedDoc.from_json(d.to_json()) == d
```

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_text.py -q` → FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: 구현**

```python
# src/reg/structure/__init__.py
```

```python
# src/reg/structure/model.py
from dataclasses import asdict, dataclass, field
from datetime import date


@dataclass
class Block:
    text: str
    page: int | None = None
    bbox: tuple | None = None


@dataclass
class Prov:
    path: str
    unit: str  # chapter|section|article|paragraph|item|subitem|supplement|supp_article|annex
    label: str
    heading: str | None = None
    text: str = ""
    parent: str | None = None
    annotations: list[str] = field(default_factory=list)
    deleted: bool = False
    effective_override: date | None = None
    anchor: dict | None = None
    meta: dict = field(default_factory=dict)


@dataclass
class HistEntry:
    kind: str
    date: date
    number: str | None = None


@dataclass
class ParsedDoc:
    title: str
    class_code: str | None
    history: list[HistEntry]
    provisions: list[Prov]
    meta: dict = field(default_factory=dict)

    def get(self, path: str) -> Prov | None:
        return next((p for p in self.provisions if p.path == path), None)

    def children(self, path: str) -> list[Prov]:
        return [p for p in self.provisions if p.parent == path]

    def supplements(self) -> list[Prov]:
        return [p for p in self.provisions if p.unit == "supplement"]

    def to_json(self) -> dict:
        d = asdict(self)
        for h in d["history"]:
            h["date"] = h["date"].isoformat()
        for p in d["provisions"]:
            if p["effective_override"]:
                p["effective_override"] = p["effective_override"].isoformat()
        return d

    @classmethod
    def from_json(cls, d: dict) -> "ParsedDoc":
        hist = [HistEntry(h["kind"], date.fromisoformat(h["date"]), h["number"]) for h in d["history"]]
        provs = []
        for p in d["provisions"]:
            p = dict(p)
            if p["effective_override"]:
                p["effective_override"] = date.fromisoformat(p["effective_override"])
            provs.append(Prov(**p))
        return cls(d["title"], d["class_code"], hist, provs, d.get("meta", {}))
```

```python
# src/reg/structure/text.py
import re
import unicodedata
from datetime import date

_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f​﻿]")
_WS = re.compile(r"[ \t　\xa0]+")
NOTE = re.compile(r"<(?:개정|신설|본조신설|전문개정|제목개정|일부개정|삭제|타법개정)[^<>]*>"
                  r"|\[(?:본조신설|제목개정|전문개정|본조개정|종전|시행일)[^\[\]]*\]")
_DOT = re.compile(r"(?<!\d)('?\d{2}|\d{4})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})")
_YMD8 = re.compile(r"(?<!\d)(\d{4})(\d{2})(\d{2})(?!\d)")
KO_DATE = re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")


def clean(s: str) -> str:
    s = unicodedata.normalize("NFC", s or "")
    s = _CTRL.sub("", s)
    return _WS.sub(" ", s).strip()


def split_notes(s: str) -> tuple[str, list[str]]:
    notes = NOTE.findall(s)
    return clean(NOTE.sub(" ", s)), notes


def _mk(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_dot_date(s: str) -> date | None:
    m = _DOT.search(s or "")
    if m:
        y = m[1].lstrip("'")
        year = int(y) if len(y) == 4 else (1900 + int(y) if int(y) >= 50 else 2000 + int(y))
        return _mk(year, int(m[2]), int(m[3]))
    m = _YMD8.search(s or "")
    if m:
        return _mk(int(m[1]), int(m[2]), int(m[3]))
    m = KO_DATE.search(s or "")
    return _mk(int(m[1]), int(m[2]), int(m[3])) if m else None


def _hangul(c: str) -> bool:
    return "가" <= c <= "힣"


class Joiner:
    """PDF 줄바꿈 이어붙이기. 원문 띄어쓰기 정보가 없어서 문서 안 어절 사전으로 추정한다.

    사전 = 각 줄의 안쪽 어절(줄 첫·끝 어절은 잘린 조각일 수 있어 뺀다).
    한글-한글 경계: 합친 어절이 사전에 있으면 붙이고, 앞 조각이 완전한 어절이면 띄우고, 그 밖에는 붙인다.
    """

    def __init__(self, lines: list[str]):
        self.vocab: set[str] = set()
        for ln in lines:
            toks = ln.split()
            self.vocab.update(toks[1:-1])

    def join(self, prev: str, nxt: str) -> str:
        if not prev:
            return nxt
        if not nxt:
            return prev
        a, b = prev[-1], nxt[0]
        if not (_hangul(a) and _hangul(b)):
            return prev + " " + nxt
        last, first = prev.split()[-1], nxt.split()[0]
        if last + first in self.vocab:
            return prev + nxt
        if last in self.vocab:
            return prev + " " + nxt
        return prev + nxt
```

- [ ] **Step 4: 통과 확인 후 커밋**

Run: `uv run pytest tests/test_text.py -q` → 5 PASS

```bash
git add src/reg/structure tests/test_text.py
git commit -m "feat(structure): document model and Korean text utilities"
```

---

### Task 3: 추출기(HWP·HWPX·PDF)와 내부규정 구조 파서

**Files:**
- Create: `src/reg/extract/__init__.py`, `src/reg/extract/hwp.py`, `src/reg/extract/hwpx.py`, `src/reg/extract/pdf.py`, `src/reg/structure/parse.py`, `tests/fixtures/samples/` (`data/samples/kasi-yeobi-339.pdf`, `data/samples/nst-yeobi-18.hwp` 복사), `tests/test_extract.py`, `tests/test_parse.py`
- Modify: `pyproject.toml` (의존성 `pdfplumber>=0.11`, `olefile>=0.47` 추가)

**Interfaces:**
- Produces:
  - `extract(data: bytes, mime: str, filename: str) -> list[Block]`
    - mime 값: `application/pdf`, `application/x-hwp`, `application/hwp+zip`
    - 그 밖의 mime이면 `ValueError`
  - `extract_hwp(data) -> list[Block]`: 문단마다 Block 하나, page와 bbox는 None
  - `extract_hwpx(data) -> list[Block]`
  - `extract_pdf(data) -> list[Block]`: 줄마다 Block 하나, page는 1부터 시작
    - 반복 머리글·꼬리글과 쪽번호를 뺀다.
  - `parse_blocks(blocks: list[Block]) -> ParsedDoc`
    - `meta["stats"] = {"articles", "paragraphs", "items", "supplements", "annexes", "unparsed_lines"}`

- [ ] **Step 1: 샘플 복사와 실패하는 테스트 작성**

```bash
mkdir -p tests/fixtures/samples && cp data/samples/kasi-yeobi-339.pdf data/samples/nst-yeobi-18.hwp tests/fixtures/samples/
uv add "pdfplumber>=0.11" "olefile>=0.47"
```

```python
# tests/test_extract.py
import io
import zipfile
from pathlib import Path

import pytest

from reg.extract import extract

S = Path(__file__).parent / "fixtures" / "samples"


def test_hwp_paragraphs_are_clean():
    blocks = extract((S / "nst-yeobi-18.hwp").read_bytes(), "application/x-hwp", "a.hwp")
    texts = [b.text for b in blocks]
    assert "여비규정" in texts[:5]
    assert any(t.startswith("제9조의2(국내여비의 정산 및 지급)") for t in texts)
    assert all("捤" not in t and "\x0b" not in t for t in texts)


def test_pdf_lines_drop_running_header_and_page_numbers():
    blocks = extract((S / "kasi-yeobi-339.pdf").read_bytes(), "application/pdf", "a.pdf")
    texts = [b.text for b in blocks]
    assert not any(t in ("- 12 -", "2120 여비규정", "여비규정 2120") for t in texts)
    hit = next(b for b in blocks if b.text.startswith("제 27 조 (출장증빙의 제출)"))
    assert hit.page == 12 and len(hit.bbox) == 4


def test_hwpx_paragraphs():
    sec = ('<hs:sec xmlns:hs="urn:hs" xmlns:hp="urn:hp"><hp:p><hp:run><hp:t>제1조(목적) 이 </hp:t>'
           '<hp:t>규정은</hp:t></hp:run></hp:p><hp:p><hp:run><hp:t>②둘째</hp:t></hp:run></hp:p></hs:sec>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Contents/section0.xml", sec)
    blocks = extract(buf.getvalue(), "application/hwp+zip", "a.hwpx")
    assert [b.text for b in blocks] == ["제1조(목적) 이 규정은", "②둘째"]


def test_unknown_mime_rejected():
    with pytest.raises(ValueError):
        extract(b"x", "text/html", "a.html")
```

```python
# tests/test_parse.py
from datetime import date
from pathlib import Path

from reg.extract import extract
from reg.structure.model import Block
from reg.structure.parse import parse_blocks

S = Path(__file__).parent / "fixtures" / "samples"


def kasi():
    return parse_blocks(extract((S / "kasi-yeobi-339.pdf").read_bytes(), "application/pdf", "a.pdf"))


def nst():
    return parse_blocks(extract((S / "nst-yeobi-18.hwp").read_bytes(), "application/x-hwp", "a.hwp"))


def test_kasi_header_and_history():
    d = kasi()
    assert d.title == "여비규정" and d.class_code == "2120"
    assert d.history[0].kind == "제정" and d.history[0].date == date(1999, 12, 21)
    assert (d.history[-1].kind, d.history[-1].date, d.history[-1].number) == ("개정", date(2024, 1, 17), "339")


def test_kasi_chapters_from_body_not_toc():
    d = kasi()
    chapters = [p for p in d.provisions if p.unit == "chapter"]
    assert [c.path for c in chapters] == ["c1", "c2", "c3", "c4", "c5", "c6"]
    assert chapters[0].heading == "총칙" and chapters[0].anchor["page"] > 3  # 목차(앞쪽)가 아니라 본문 위치


def test_kasi_article_27_paragraphs():
    d = kasi()
    a27 = d.get("a27")
    assert a27.heading == "출장증빙의 제출" and a27.parent == "c6" and a27.anchor["page"] == 12
    p1 = d.get("a27.p1")
    assert p1.label == "①" and "출장 종료일 다음 날을 기점으로 7일 이내에 출장을 확인할 수 있는 증빙서를" in p1.text
    assert any("2020.11.6" in n for n in p1.annotations) and "<개정" not in p1.text
    assert any("본조신설" in n for n in a27.annotations)
    assert [p.path for p in d.children("a27")] == ["a27.p1", "a27.p2", "a27.p3"]


def test_kasi_branch_article_and_items():
    d = kasi()
    assert d.get("a4-2").heading == "여비의 정산"
    items = d.children("a26.p1")
    assert [i.label for i in items][:3] == ["1.", "2.", "3."] and items[1].deleted


def test_reference_at_line_start_is_not_an_article():
    blocks = [Block("제1조(목적) 이 규정은 목적을 정한다."), Block("제2조(적용) ① 이 규정은"),
              Block("제13조의 근무지내 출장에 적용한다."), Block("제3조(기타) 끝.")]
    d = parse_blocks(blocks)
    assert [p.path for p in d.provisions if p.unit == "article"] == ["a1", "a2", "a3"]
    assert "제13조의 근무지내 출장" in d.get("a2.p1").text


def test_supplement_articles_do_not_override_body():
    d = kasi()
    assert d.get("a1").heading == "목적"
    supps = d.supplements()
    assert supps[-1].path == "supp@2024-01-17" and "2024년 1월 17일부터 시행한다" in supps[-1].text


def test_nst_inline_paragraphs_deleted_article_and_duplicate_supplements():
    d = nst()
    assert d.title == "여비규정"
    assert [p.path for p in d.children("a4")] == ["a4.p1", "a4.p2"]
    assert d.get("a7").deleted
    assert "10일 이내" in d.get("a9-2").text
    paths = [s.path for s in d.supplements()]
    assert "supp@2023-12-21" in paths and "supp@2023-12-21~2" in paths
    assert len(paths) == len(set(paths))
```

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_extract.py tests/test_parse.py -q` → FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: 추출기 구현**

```python
# src/reg/extract/__init__.py
from reg.structure.model import Block


def extract(data: bytes, mime: str, filename: str) -> list[Block]:
    if mime == "application/pdf":
        from reg.extract.pdf import extract_pdf
        return extract_pdf(data)
    if mime == "application/x-hwp":
        from reg.extract.hwp import extract_hwp
        return extract_hwp(data)
    if mime == "application/hwp+zip":
        from reg.extract.hwpx import extract_hwpx
        return extract_hwpx(data)
    raise ValueError(f"지원하지 않는 형식: {mime} ({filename})")
```

```python
# src/reg/extract/hwp.py
"""HWP 5.0 본문 문단 추출 (OLE BodyText/Section*, HWPTAG_PARA_TEXT=67)."""
import io
import struct
import zlib

import olefile

from reg.structure.model import Block
from reg.structure.text import clean

PARA_TEXT = 67
# HWP 5.0 문자 컨트롤: 확장·인라인 컨트롤은 WCHAR 8개를 차지한다
_WIDE = {1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23}


def _para_text(raw: bytes) -> str:
    chars = struct.unpack(f"<{len(raw) // 2}H", raw[: len(raw) // 2 * 2])
    out, i = [], 0
    while i < len(chars):
        c = chars[i]
        if c in _WIDE:
            i += 8
            continue
        if c >= 32:
            out.append(chr(c))
        elif c in (10, 13):
            out.append(" ")
        i += 1
    return "".join(out)


def extract_hwp(data: bytes) -> list[Block]:
    ole = olefile.OleFileIO(io.BytesIO(data))
    compressed = ole.openstream("FileHeader").read()[36] & 1
    sections = sorted((e for e in ole.listdir() if e[0] == "BodyText"), key=lambda e: int(e[1][7:]))
    blocks = []
    for sec in sections:
        buf = ole.openstream(sec).read()
        if compressed:
            buf = zlib.decompress(buf, -15)
        i = 0
        while i + 4 <= len(buf):
            header = struct.unpack_from("<I", buf, i)[0]
            tag, size = header & 0x3FF, (header >> 20) & 0xFFF
            i += 4
            if size == 0xFFF:
                size = struct.unpack_from("<I", buf, i)[0]
                i += 4
            if tag == PARA_TEXT:
                t = clean(_para_text(buf[i:i + size]))
                if t:
                    blocks.append(Block(t))
            i += size
    return blocks
```

```python
# src/reg/extract/hwpx.py
"""HWPX(OWPML, zip) 본문 문단 추출. 표 안의 문단은 바깥 문단과 섞지 않고 따로 낸다."""
import io
import re
import xml.etree.ElementTree as ET
import zipfile

from reg.structure.model import Block
from reg.structure.text import clean


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _walk(elem, buf: list[str] | None, out: list[str]) -> None:
    if _local(elem.tag) == "p":
        mine: list[str] = []
        for child in elem:
            _walk(child, mine, out)
        t = clean("".join(mine))
        if t:
            out.append(t)
        return
    if _local(elem.tag) == "t" and buf is not None:
        buf.append(elem.text or "")
    for child in elem:
        _walk(child, buf, out)
        if _local(elem.tag) == "t" and buf is not None and child.tail:
            buf.append(child.tail)


def extract_hwpx(data: bytes) -> list[Block]:
    z = zipfile.ZipFile(io.BytesIO(data))
    names = sorted((n for n in z.namelist() if re.match(r"Contents/section\d+\.xml$", n)),
                   key=lambda n: int(re.search(r"(\d+)", n)[1]))
    out: list[str] = []
    for n in names:
        _walk(ET.fromstring(z.read(n)), None, out)
    return [Block(t) for t in out]
```

```python
# src/reg/extract/pdf.py
"""텍스트 PDF 줄 추출. 반복 머리글·꼬리글·쪽번호 제거, 줄마다 쪽·bbox 보존."""
import io
import re
from collections import Counter

import pdfplumber

from reg.structure.model import Block
from reg.structure.text import clean

PAGE_NO = re.compile(r"^[-–]\s*\d+\s*[-–]$|^\d+\s*/\s*\d+$")


def extract_pdf(data: bytes) -> list[Block]:
    pages: list[list[Block]] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for no, page in enumerate(pdf.pages, 1):
            lines = []
            for ln in page.extract_text_lines(strip=True):
                t = clean(ln["text"])
                if t:
                    lines.append(Block(t, no, (round(ln["x0"], 1), round(ln["top"], 1),
                                               round(ln["x1"], 1), round(ln["bottom"], 1))))
            pages.append(lines)
    # 머리글·꼬리글: 여러 쪽의 첫 줄·끝 줄에 반복되는 같은 텍스트
    edge = Counter()
    for lines in pages:
        for b in lines[:2] + lines[-2:]:
            edge[b.text] += 1
    running = {t for t, n in edge.items() if n >= 3 and n >= len(pages) * 0.3}
    return [b for lines in pages for b in lines if b.text not in running and not PAGE_NO.match(b.text)]
```

- [ ] **Step 4: 구조 파서 구현**

```python
# src/reg/structure/parse.py
"""내부규정 공통 구조 파서: Block 줄/문단 → ParsedDoc.

머리부(제목·원규분류·개정 이력·목차) → 본문(장·절·조·항·호·목) → 부칙 → 별표·별지 순서로 읽는다.
본문 시작 = 제목 괄호가 있는 첫 조문(목차 줄은 괄호가 없다), 그 앞의 가장 가까운 '제1장'이 있으면 거기부터.
"""
import re

from reg.structure.model import Block, HistEntry, ParsedDoc, Prov
from reg.structure.text import Joiner, clean, parse_dot_date, split_notes

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
RE_CHAPTER = re.compile(r"^제\s*(\d+)\s*장\s*(.{0,30})$")
RE_SECTION = re.compile(r"^제\s*(\d+)\s*절\s*(.{0,30})$")
RE_ARTICLE = re.compile(r"^제\s*(\d+)\s*조(?:\s*의\s*(\d+))?\s*(?:\(\s*([^()]{1,40}?)\s*\))?\s*(.*)$")
RE_SUPPL = re.compile(r"^부\s*칙\s*(?:[<〈(](.*?)[>〉)])?\s*(.*)$")
RE_ANNEX = re.compile(r"^[<\[〈]?\s*(별\s*표|별\s*지)\s*(?:제\s*)?(\d+)\s*(?:호)?(?:\s*의\s*(\d+))?\s*(?:서식)?\s*[>\]〉]?\s*(.*)$")
RE_ITEM = re.compile(r"^(\d+)(?:\s*의\s*(\d+))?\.\s*(.*)$")
RE_SUB = re.compile(r"^([가-하])\.\s*(.*)$")
RE_HIST = re.compile(r"^(제\s*정|전\s*부\s*개\s*정|일\s*부\s*개\s*정|개\s*정|폐\s*지)\s*"
                     r"(\d{4}\s*\.\s*\d{1,2}\s*\.\s*\d{1,2})\s*\.?\s*(?:(?:규|훈령|예규|규정)?\s*제?\s*(\d+)\s*호)?")
RE_CLASS = re.compile(r"원규\s*분류\s*(?:기호)?\s*[:：]\s*([\w-]+)")
RE_LEADER = re.compile(r"[·.…]{2,}|·\s*·|^[·\s]+$|\s·$")
INLINE_PARA = re.compile(r"(?<=[.。>\]」)])\s*(?=[①-⑳])")


def _article_key(no: str, sub: str | None) -> str:
    return f"a{int(no)}" + (f"-{int(sub)}" if sub else "")


def _num(no: str, sub: str | None) -> tuple[int, int]:
    return int(no), int(sub or 0)


def _despace_title(s: str) -> str:
    toks = s.split()
    return "".join(toks) if toks and all(len(t) == 1 for t in toks) else s


class _Builder:
    def __init__(self, joiner: Joiner):
        self.j = joiner
        self.provs: list[Prov] = []
        self.chapter: str | None = None
        self.section: str | None = None
        self.article: Prov | None = None
        self.para: Prov | None = None
        self.item: Prov | None = None
        self.cur: Prov | None = None
        self.last_art = (0, 0)
        self.last_chapter = 0
        self.supp: Prov | None = None
        self.supp_dates: dict[str, int] = {}
        self.unparsed = 0

    def add(self, p: Prov, b: Block) -> Prov:
        if b.page is not None:
            p.anchor = {"page": b.page, "bbox": list(b.bbox) if b.bbox else None}
        self.provs.append(p)
        self.cur = p
        return p

    def append_text(self, text: str) -> None:
        if self.cur is None:
            self.unparsed += 1
            return
        self.cur.text = self.j.join(self.cur.text, text) if self.cur.text else text

    def scope(self) -> str | None:
        return self.supp.path if self.supp else None


def _finish(p: Prov) -> None:
    text, notes = split_notes(p.text)
    p.text, p.annotations = text, p.annotations + notes
    if re.fullmatch(r"삭\s*제\s*\.?", text or "") or (p.deleted and not text):
        p.deleted, p.text = True, "삭제"


def _header(blocks: list[Block]) -> tuple[str, str | None, list[HistEntry]]:
    title, code, hist = "", None, []
    for b in blocks:
        t = b.text
        if m := RE_CLASS.search(t):
            code = m[1]
            continue
        if m := RE_HIST.match(t):
            hist.append(HistEntry(re.sub(r"\s+", "", m[1]), parse_dot_date(m[2]), m[3]))
            continue
        if not title and not RE_LEADER.search(t) and not re.fullmatch(r"[\d\s.-]+", t) and "목" not in t[:2]:
            title = _despace_title(re.sub(r"\(\s*원규분류.*$", "", t).strip())
    return title, code, hist


def _body_start(blocks: list[Block]) -> int:
    first = next((i for i, b in enumerate(blocks)
                  if (m := RE_ARTICLE.match(b.text)) and m[3] and not RE_LEADER.search(b.text)), None)
    if first is None:
        return len(blocks)
    for i in range(first - 1, max(first - 4, -1), -1):
        if (m := RE_CHAPTER.match(blocks[i].text)) and int(m[1]) == 1:
            return i
    return first


def _pre_split(blocks: list[Block]) -> list[Block]:
    """한 문단에 이어 붙은 항(…한다.②…)을 줄로 나눈다 (HWP)."""
    out = []
    for b in blocks:
        parts = INLINE_PARA.split(b.text)
        out.extend(Block(p.strip(), b.page, b.bbox) for p in parts if p.strip())
    return out


def parse_blocks(blocks: list[Block]) -> ParsedDoc:
    blocks = [b for b in blocks if b.text]
    start = _body_start(blocks)
    title, code, hist = _header(blocks[:start])
    body = [b for b in _pre_split(blocks[start:]) if not RE_LEADER.search(b.text) or RE_ARTICLE.match(b.text)]
    B = _Builder(Joiner([b.text for b in body]))
    annexes = 0
    in_annex = False

    for b in body:
        t = b.text
        if m := RE_ANNEX.match(t):
            if t.lstrip()[:1] in "<[〈" or m[4] == "" or in_annex or B.supp is not None:
                kind = "annex" if "표" in m[1] else "form"
                key = f"{kind}{int(m[2])}" + (f"-{int(m[3])}" if m[3] else "")
                if any(p.path == key for p in B.provs):
                    key = f"{key}~{sum(1 for p in B.provs if p.path.startswith(key)) + 1}"
                label = ("별표" if kind == "annex" else "별지") + f" 제{int(m[2])}호" + (f"의{int(m[3])}" if m[3] else "")
                B.add(Prov(key, "annex", label, heading=clean(m[4]) or None), b)
                in_annex, annexes = True, annexes + 1
                continue
        if in_annex:
            B.append_text(t)
            continue
        if m := RE_SUPPL.match(t):
            d = parse_dot_date(m[1] or "")
            base = f"supp@{d.isoformat()}" if d else f"supp#{len(B.supp_dates) + 1}"
            n = B.supp_dates.get(base, 0) + 1
            B.supp_dates[base] = n
            path = base if n == 1 else f"{base}~{n}"
            B.supp = B.add(Prov(path, "supplement", "부칙", meta={"date": d.isoformat() if d else None}), b)
            B.article = B.para = B.item = None
            if m[2]:
                B.append_text(m[2])
            continue
        if B.supp is None and (m := RE_CHAPTER.match(t)) and int(m[1]) == B.last_chapter + 1:
            B.last_chapter = int(m[1])
            B.chapter, B.section = f"c{int(m[1])}", None
            B.add(Prov(B.chapter, "chapter", f"제{int(m[1])}장", heading=_despace_title(clean(m[2])) or None), b)
            B.cur = None
            continue
        if B.supp is None and B.chapter and (m := RE_SECTION.match(t)):
            B.section = f"{B.chapter}-s{int(m[1])}"
            B.add(Prov(B.section, "section", f"제{int(m[1])}절", heading=clean(m[2]) or None, parent=B.chapter), b)
            B.cur = None
            continue
        if (m := RE_ARTICLE.match(t)) and (m[3] or re.match(r"삭\s*제", m[4] or "")):
            num = _num(m[1], m[2])
            in_supp = B.supp is not None
            if in_supp or num > B.last_art:
                key = _article_key(m[1], m[2])
                if in_supp:
                    key, parent, unit = f"{B.supp.path}/{key}", B.supp.path, "supp_article"
                else:
                    parent, unit = B.section or B.chapter, "article"
                    B.last_art = num
                label = f"제{int(m[1])}조" + (f"의{int(m[2])}" if m[2] else "")
                B.article = B.add(Prov(key, unit, label, heading=clean(m[3]) if m[3] else None, parent=parent), b)
                B.para = B.item = None
                rest = (m[4] or "").strip()
                if rest and rest[0] in CIRCLED:
                    _para(B, rest, b)
                elif rest:
                    B.append_text(rest)
                continue
        if B.article is not None and t[0] in CIRCLED:
            _para(B, t, b)
            continue
        if B.article is not None and (m := RE_ITEM.match(t)):
            parent = B.para or B.article
            key = f"{parent.path}.i{int(m[1])}" + (f"-{int(m[2])}" if m[2] else "")
            if any(p.path == key for p in B.provs):
                B.append_text(t)
                continue
            B.item = B.add(Prov(key, "item", f"{int(m[1])}." if not m[2] else f"{int(m[1])}의{int(m[2])}.",
                                parent=parent.path), b)
            B.append_text(m[3])
            continue
        if B.item is not None and (m := RE_SUB.match(t)):
            key = f"{B.item.path}.s{m[1]}"
            B.add(Prov(key, "subitem", f"{m[1]}.", parent=B.item.path), b)
            B.append_text(m[2])
            continue
        B.append_text(t)

    for p in B.provs:
        _finish(p)
    st = {u: sum(1 for p in B.provs if p.unit == k) for u, k in
          [("articles", "article"), ("paragraphs", "paragraph"), ("items", "item"), ("supplements", "supplement"),
           ("annexes", "annex")]}
    st["unparsed_lines"] = B.unparsed
    return ParsedDoc(title, code, [h for h in hist if h.date], B.provs, {"stats": st})


def _para(B: _Builder, t: str, b: Block) -> None:
    n = CIRCLED.index(t[0]) + 1
    key = f"{B.article.path}.p{n}"
    if any(p.path == key for p in B.provs):
        B.append_text(t)
        return
    B.para = B.add(Prov(key, "paragraph", t[0], parent=B.article.path), b)
    B.item = None
    B.append_text(t[1:].strip())
```

- [ ] **Step 5: 통과 확인 후 커밋**

Run: `uv run pytest tests/test_extract.py tests/test_parse.py -q` → 11 PASS

계획의 정규식이 실파일에서 틀린 경우의 처리 원칙:
- 테스트 기대값은 실제 원문 기준이므로 바꾸지 않는다.
- 파서를 고치고, 그 내용을 ledger에 `Ruling`으로 남긴다.

```bash
git add pyproject.toml uv.lock src/reg/extract src/reg/structure/parse.py tests/fixtures/samples tests/test_extract.py tests/test_parse.py
git commit -m "feat(structure): HWP/HWPX/PDF extractors and regulation structure parser"
```

---

### Task 4: 법령 XML 파서

**Files:**
- Create: `src/reg/structure/law_xml.py`, `tests/test_law_xml.py`

**Interfaces:**
- Produces: `parse_law_xml(data: bytes) -> ParsedDoc`
  - `meta`: `{"law_id", "promulgated_on", "effective_on", "amendment_kind", "kind", "promulgation_no"}`. 날짜는 iso 문자열이다.
  - 조문
    - `조문여부=전문`이면 장으로 본다(`c{n}`). 절이면 `c{n}-s{m}`.
    - 그 밖에는 조로 본다(`a{n}` / `a{n}-{가지번호}`).
    - `조문시행일자`가 법령 시행일과 다르면 `effective_override`에 넣는다.
  - 항: `항번호`가 있으면 `{조}.p{n}`, 없는 항(호만 담은 묶음)은 호를 조에 바로 붙인다.
  - 호: `{부모}.i{n}`
  - 목: `{호}.s{가}`
  - 부칙
    - `부칙단위` 하나가 `supplement` 하나다.
    - 경로는 `supp@{부칙공포일자}`이고 같은 날짜가 겹치면 `~n`을 붙인다.
    - 본문은 `부칙내용`이다.

- [ ] **Step 1: 실패하는 테스트**

```python
# tests/test_law_xml.py
from datetime import date
from pathlib import Path

from reg.structure.law_xml import parse_law_xml

FX = Path(__file__).parent / "fixtures"


def doc():
    return parse_law_xml((FX / "lawgo_service_283849.xml").read_bytes())


def test_law_basic_info():
    d = doc()
    assert d.title == "국가연구개발혁신법"
    assert d.meta["law_id"] == "013774" and d.meta["effective_on"] == "2026-09-11"
    assert d.meta["promulgated_on"] == "2026-03-10" and d.meta["amendment_kind"] == "일부개정"


def test_law_structure():
    d = doc()
    assert d.get("c1").unit == "chapter" and d.get("c1").heading == "총칙"
    a2 = d.get("a2")
    assert a2.heading == "정의" and a2.parent == "c1"
    assert d.get("a2.i1").label == "1." and d.get("a2.i1").text.startswith('"국가연구개발사업"이란')
    assert d.get("a9.p1").label == "①"
    assert any("2026.3.10" in n for n in a2.annotations)


def test_law_supplements_unique_paths():
    d = doc()
    paths = [s.path for s in d.supplements()]
    assert paths and len(paths) == len(set(paths)) and paths[0] == "supp@2020-06-09"
```

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_law_xml.py -q` → FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: 구현**

```python
# src/reg/structure/law_xml.py
"""law.go.kr lawService XML → ParsedDoc. 조문·항·호·목·부칙이 태그로 나뉘어 있어 그대로 옮긴다."""
import re
import xml.etree.ElementTree as ET

from reg.structure.model import ParsedDoc, Prov
from reg.structure.text import clean, parse_dot_date, split_notes

RE_HEAD = re.compile(r"^제\s*\d+\s*조(?:\s*의\s*\d+)?\s*(?:\([^()]*\))?\s*")
RE_CH = re.compile(r"제\s*(\d+)\s*(장|절)\s*(.*)")


def _txt(e, tag: str) -> str:
    return clean(e.findtext(tag) or "")


def _iso(s: str) -> str | None:
    d = parse_dot_date(s)
    return d.isoformat() if d else None


def _strip_marker(s: str, marker: str) -> str:
    return s[len(marker):].strip() if marker and s.startswith(marker) else s


def parse_law_xml(data: bytes) -> ParsedDoc:
    root = ET.fromstring(data)
    info = root.find("기본정보")
    eff = _iso(_txt(info, "시행일자"))
    meta = {"law_id": _txt(info, "법령ID"), "promulgated_on": _iso(_txt(info, "공포일자")), "effective_on": eff,
            "amendment_kind": _txt(info, "제개정구분") or None, "kind": _txt(info, "법종구분") or None,
            "promulgation_no": _txt(info, "공포번호") or None}
    provs: list[Prov] = []
    chapter = None

    def add(p: Prov, raw: str) -> Prov:
        p.text, notes = split_notes(raw)
        p.annotations += notes
        if p.text in ("삭제", "삭제."):
            p.deleted = True
        provs.append(p)
        return p

    for u in root.iter("조문단위"):
        if _txt(u, "조문여부") == "전문":
            m = RE_CH.search(_txt(u, "조문내용"))
            if m and m[2] == "장":
                chapter = f"c{int(m[1])}"
                provs.append(Prov(chapter, "chapter", f"제{int(m[1])}장", heading=clean(m[3]) or None))
            elif m and chapter:
                provs.append(Prov(f"{chapter}-s{int(m[1])}", "section", f"제{int(m[1])}절",
                                  heading=clean(m[3]) or None, parent=chapter))
            continue
        no, branch = _txt(u, "조문번호"), _txt(u, "조문가지번호")
        key = f"a{int(no)}" + (f"-{int(branch)}" if branch and branch != "0" else "")
        label = f"제{int(no)}조" + (f"의{int(branch)}" if branch and branch != "0" else "")
        lead = RE_HEAD.sub("", _txt(u, "조문내용"), count=1)
        art = add(Prov(key, "article", label, heading=_txt(u, "조문제목") or None, parent=chapter), lead)
        ae = _iso(_txt(u, "조문시행일자"))
        if ae and ae != eff:
            art.effective_override = parse_dot_date(ae)
        for h in u.findall("항"):
            hno = _txt(h, "항번호")
            parent = key
            if hno:
                parent = f"{key}.p{'①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳'.index(hno[0]) + 1}"
                add(Prov(parent, "paragraph", hno[0], parent=key), _strip_marker(_txt(h, "항내용"), hno))
            for ho in h.findall("호"):
                hono = _txt(ho, "호번호")
                m = re.match(r"(\d+)(?:의(\d+))?", hono)
                ikey = f"{parent}.i{int(m[1])}" + (f"-{int(m[2])}" if m and m[2] else "") if m else f"{parent}.i?"
                add(Prov(ikey, "item", hono, parent=parent), _strip_marker(_txt(ho, "호내용"), hono))
                for mo in ho.findall("목"):
                    mono = _txt(mo, "목번호")
                    add(Prov(f"{ikey}.s{mono[:1]}", "subitem", mono, parent=ikey),
                        _strip_marker(_txt(mo, "목내용"), mono))
    seen: dict[str, int] = {}
    for s in root.iter("부칙단위"):
        d = _iso(_txt(s, "부칙공포일자"))
        base = f"supp@{d}" if d else f"supp#{len(seen) + 1}"
        seen[base] = seen.get(base, 0) + 1
        path = base if seen[base] == 1 else f"{base}~{seen[base]}"
        provs.append(Prov(path, "supplement", "부칙", text=clean(s.findtext("부칙내용") or ""),
                          meta={"date": d, "number": _txt(s, "부칙공포번호") or None}))
    return ParsedDoc(clean(info.findtext("법령명_한글") or ""), None, [], provs, meta)
```

- [ ] **Step 4: 통과 확인 후 커밋**

Run: `uv run pytest tests/test_law_xml.py -q` → 3 PASS

```bash
git add src/reg/structure/law_xml.py tests/test_law_xml.py
git commit -m "feat(structure): law.go.kr XML to ParsedDoc"
```

---

### Task 5: 시행일 판정기

**Files:**
- Create: `src/reg/structure/effective.py`, `tests/test_effective.py`

**Interfaces:**
- Produces:
  - `Effective(effective_from: date | None, basis: str, status: str, promulgated_on: date | None, overrides: dict[str, date])` (dataclass)
  - `resolve(doc: ParsedDoc, alio_date: date | None = None, filename: str = "") -> Effective`
- 규칙
  - **법령**(`doc.meta`에 `effective_on`이 있음)이면 `basis="api"`, `status="CONFIRMED"`이고 `promulgated_on`은 meta 값을 쓴다.
  - **부칙 시행일**은 날짜가 가장 늦은 부칙(같으면 뒤쪽)의 본문에서 찾는다. 순서대로 확인한다.
    1. `공포한 날(…)부터` 괄호 안 날짜
    2. `YYYY년 M월 D일부터 시행` 또는 `YYYY. M. D.부터 시행`
    3. `공포한 날부터` 또는 `결재…날부터`이면 그 부칙 머리 날짜
  - **조항별 시행일**: `다만, 제N조(의M)…는 YYYY년 M월 D일부터` 문장에서 조 경로별 날짜를 `overrides`에 담는다.
  - **promulgated_on**은 개정 이력표의 마지막 날짜이고, 없으면 마지막 부칙 머리 날짜다.
  - **status**
    - `CONFIRMED`: 부칙으로 시행일을 찾았고 아래 두 조건을 모두 만족할 때
      - 이력 마지막 날짜와 부칙 머리 날짜가 같다(둘 중 하나가 없어도 된다).
      - `alio_date`가 없거나, 이력 마지막 날짜·시행일 중 하나와 같다.
    - `CONFLICT`: 이력 마지막 날짜와 부칙 머리 날짜가 둘 다 있고 서로 다를 때, 또는 `alio_date`가 이력 날짜·시행일 어느 쪽과도 다를 때
    - `UNCERTAIN`: 근거가 history, alio, filename, none일 때

- [ ] **Step 1: 실패하는 테스트**

```python
# tests/test_effective.py
from datetime import date
from pathlib import Path

from reg.extract import extract
from reg.structure.effective import resolve
from reg.structure.model import HistEntry, ParsedDoc, Prov
from reg.structure.parse import parse_blocks

S = Path(__file__).parent / "fixtures" / "samples"


def test_kasi_real_file_confirmed():
    d = parse_blocks(extract((S / "kasi-yeobi-339.pdf").read_bytes(), "application/pdf", "a.pdf"))
    e = resolve(d, alio_date=date(2024, 1, 17))
    assert (e.effective_from, e.basis, e.status) == (date(2024, 1, 17), "supplement", "CONFIRMED")


def test_nst_promulgation_date_in_parentheses():
    d = parse_blocks(extract((S / "nst-yeobi-18.hwp").read_bytes(), "application/x-hwp", "a.hwp"))
    e = resolve(d)
    assert e.effective_from == date(2024, 1, 2) and e.promulgated_on == date(2023, 12, 21)
    assert e.status == "CONFIRMED"


def doc(hist, supps):
    provs = [Prov(f"supp@{dt}", "supplement", "부칙", text=t, meta={"date": dt}) for dt, t in supps]
    return ParsedDoc("x", None, [HistEntry("개정", h) for h in hist], provs)


def test_publication_day_uses_supplement_header_date():
    e = resolve(doc([date(2022, 3, 1)], [("2022-03-01", "이 규정은 공포한 날부터 시행한다.")]))
    assert (e.effective_from, e.status) == (date(2022, 3, 1), "CONFIRMED")


def test_conflict_when_history_and_supplement_disagree():
    e = resolve(doc([date(2022, 3, 1)], [("2022-05-01", "이 규정은 2022년 5월 1일부터 시행한다.")]))
    assert e.status == "CONFLICT" and e.effective_from == date(2022, 5, 1)


def test_history_only_is_uncertain():
    e = resolve(doc([date(2021, 1, 5)], []))
    assert (e.effective_from, e.basis, e.status) == (date(2021, 1, 5), "history", "UNCERTAIN")


def test_filename_fallback_and_overrides():
    e = resolve(doc([], []), filename="연구사업 관리규정(2020년 12월 개정).pdf")
    assert e.basis == "filename" and e.effective_from is None and e.status == "UNCERTAIN"
    e2 = resolve(doc([date(2022, 1, 1)], [("2022-01-01",
        "이 규정은 2022년 1월 1일부터 시행한다. 다만, 제5조 및 제7조의2는 2022년 7월 1일부터 시행한다.")]))
    assert e2.overrides == {"a5": date(2022, 7, 1), "a7-2": date(2022, 7, 1)}


def test_law_meta_is_api_confirmed():
    d = ParsedDoc("법", None, [], [], {"effective_on": "2026-09-11", "promulgated_on": "2026-03-10"})
    e = resolve(d)
    assert (e.effective_from, e.basis, e.status, e.promulgated_on) == (
        date(2026, 9, 11), "api", "CONFIRMED", date(2026, 3, 10))
```

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_effective.py -q` → FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: 구현**

```python
# src/reg/structure/effective.py
"""시행일 판정 (spec 6.5): 부칙 > 개정 이력표 > ALIO 개정일 > 파일명."""
import re
from dataclasses import dataclass, field
from datetime import date

from reg.structure.model import ParsedDoc
from reg.structure.text import KO_DATE, parse_dot_date

DATE_ANY = r"(\d{4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일|\d{4}\s*\.\s*\d{1,2}\s*\.\s*\d{1,2}\s*\.?)"
RE_PAREN = re.compile(r"공포한\s*날\s*[(（]\s*" + DATE_ANY + r"\s*[)）]\s*부터")
RE_FROM = re.compile(DATE_ANY + r"\s*부터\s*시행")
RE_PUB = re.compile(r"(공포한\s*날|결재[^.。]{0,30}?날)\s*부터\s*시행")
RE_BUT = re.compile(r"다만[,，]?\s*(.*?)(?:은|는)\s*" + DATE_ANY + r"\s*부터")
RE_ART = re.compile(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?")
RE_FILE = re.compile(r"(\d{4})\s*년(?:도)?\s*(\d{1,2})\s*월")


@dataclass
class Effective:
    effective_from: date | None
    basis: str
    status: str
    promulgated_on: date | None
    overrides: dict = field(default_factory=dict)


def _d(s: str) -> date | None:
    return parse_dot_date(s) if not KO_DATE.search(s) else parse_dot_date(s)


def _from_supplement(text: str, header: date | None) -> date | None:
    main = text.split("다만")[0]
    for rx in (RE_PAREN, RE_FROM):
        if m := rx.search(main):
            return _d(m[1])
    if RE_PUB.search(main):
        return header
    return None


def resolve(doc: ParsedDoc, alio_date: date | None = None, filename: str = "") -> Effective:
    if doc.meta.get("effective_on"):
        return Effective(date.fromisoformat(doc.meta["effective_on"]), "api", "CONFIRMED",
                         date.fromisoformat(doc.meta["promulgated_on"]) if doc.meta.get("promulgated_on") else None)
    hist_last = doc.history[-1].date if doc.history else None
    supps = doc.supplements()
    dated = [(date.fromisoformat(s.meta["date"]) if s.meta.get("date") else None, i, s) for i, s in enumerate(supps)]
    last = max(dated, key=lambda x: (x[0] or date.min, x[1]))[2] if dated else None
    header = date.fromisoformat(last.meta["date"]) if last is not None and last.meta.get("date") else None
    text = " ".join([last.text] + [p.text for p in doc.provisions if p.parent == last.path]) if last else ""
    eff = _from_supplement(text, header) if last else None
    overrides = {}
    for m in RE_BUT.finditer(text):
        when = _d(m[2])
        for a in RE_ART.finditer(m[1]):
            overrides[f"a{int(a[1])}" + (f"-{int(a[2])}" if a[2] else "")] = when
    promulgated = hist_last or header
    if eff is not None:
        conflict = (hist_last and header and hist_last != header) or (
            alio_date and alio_date not in {hist_last, eff})
        return Effective(eff, "supplement", "CONFLICT" if conflict else "CONFIRMED", promulgated, overrides)
    if hist_last:
        return Effective(hist_last, "history", "UNCERTAIN", promulgated, overrides)
    if alio_date:
        return Effective(alio_date, "alio", "UNCERTAIN", promulgated, overrides)
    if RE_FILE.search(filename or ""):
        return Effective(None, "filename", "UNCERTAIN", promulgated, overrides)
    return Effective(None, "none", "UNCERTAIN", promulgated, overrides)
```

- [ ] **Step 4: 통과 확인 후 커밋**

Run: `uv run pytest tests/test_effective.py -q` → 7 PASS

```bash
git add src/reg/structure/effective.py tests/test_effective.py
git commit -m "feat(structure): effective-date resolver with basis and status"
```

---

### Task 6: 적재기 (work·버전·조항 계보·변경 이력)

**Files:**
- Create: `src/reg/load/__init__.py`, `src/reg/load/loader.py`, `tests/test_loader.py`

**Interfaces:**
- Consumes: `ParsedDoc`, `Effective`
- Produces:
  - `work_key_for_regulation(conn, inst_code: str, inst_id: int, title: str, seq: str) -> str`
    - `seq`로 이미 있는 work를 찾는다.
    - 없으면 `kr/reg/{inst}/{norm_title}`로 만든다. 이름이 겹치면 `~{seq}`를 붙인다.
  - `upsert_work(conn, work_id: str, kind: str, title: str, institution_id: int | None, external_ids: dict) -> None`
  - `add_version(conn, work_id, source_document_id, doc: ParsedDoc, eff: Effective, posted_on: date | None = None) -> str`
    - version id를 돌려준다.
    - 같은 `(work_id, source_document_id)`가 이미 있으면 기존 id를 돌려준다(멱등).
  - `rebuild_work(conn, work_id, today: date) -> dict`
    - 해당 work의 조항 데이터를 지우고, 버전들을 시행일 순서로 다시 적재한다.
    - 버전마다 `effective_to`와 `version_state`를 정한다.
    - 반환값: `{"versions", "provisions", "changes"}`
- 계보 규칙
  - **기본**: 직전 버전과 같은 `path`면 같은 조항이다.
  - **번호이동 판정 대상**: `path`가 직전 버전에 없는 조/항/호 중에서, 직전 버전에서 짝을 찾지 못한 조항과 본문 정규화 해시가 같으면 `RENUMBERED`로 본다. 대상 단위는 `article`, `paragraph`, `item`이다.
  - **단위별 판정**
    - 해시와 제목이 같고 주석만 다르면 `ANNOTATION_ONLY`
    - 모두 같으면 변경 없음이다. 이전 provision_version 행을 다시 쓴다.
    - 그 밖에 내용이 다르면 `MODIFIED`
  - **새 조항과 삭제 조항**
    - 짝이 없는 새 조항은 `ADDED`다. `lineage_key`는 `{path}@{version_id}`로 정한다.
    - 직전 버전에만 있는 조항은 `DELETED`다.
  - 시행일이 없는 버전(UNDATED)은 계보 비교에서 빼고, 각자 독립된 조항을 가진다.

- [ ] **Step 1: 실패하는 테스트**

```python
# tests/test_loader.py
from datetime import date

from reg.collect.archive import store
from reg.collect.sniff import FileKind
from reg.load.loader import add_version, rebuild_work, upsert_work, work_key_for_regulation
from reg.storage.blob import LocalBlobStore
from reg.structure.effective import Effective
from reg.structure.model import ParsedDoc, Prov

PDF = FileKind("application/pdf", "pdf")


def src(conn, tmp_path, tag: bytes) -> int:
    return store(conn, LocalBlobStore(tmp_path), source="alio", url="u", content=b"%PDF" + tag, kind=PDF, meta={}).id


def doc(*arts):
    return ParsedDoc("여비규정", "2120", [], [Prov(p, "article", f"제{p[1:]}조", h, t) for p, h, t in arts])


def eff(d):
    return Effective(d, "supplement", "CONFIRMED", d)


def setup(conn, tmp_path):
    conn.execute("INSERT INTO regulation.institution (code, name, kind) VALUES ('KASI','한국천문연구원','GRI')")
    wid = work_key_for_regulation(conn, "KASI", 1, "여비 규정", "47852")
    upsert_work(conn, wid, "INTERNAL_REG", "여비규정", 1, {"alio_seq": "47852"})
    return wid


def changes(conn, wid, to):
    return sorted((r["kind"], r["path"]) for r in conn.execute(
        "SELECT c.kind, coalesce(t.path, f.path) AS path FROM regulation.provision_change c"
        " LEFT JOIN regulation.provision_version t ON t.id = c.to_pv_id"
        " LEFT JOIN regulation.provision_version f ON f.id = c.from_pv_id"
        " WHERE c.work_id = %s AND c.to_version_id = %s", (wid, to)).fetchall())


def test_work_key_is_stable_by_seq(conn, tmp_path):
    wid = setup(conn, tmp_path)
    assert wid == "kr/reg/KASI/여비규정"
    assert work_key_for_regulation(conn, "KASI", 1, "여비규정(개정)", "47852") == wid
    assert work_key_for_regulation(conn, "KASI", 1, "여비규정", "99999") == "kr/reg/KASI/여비규정~99999"


def test_versions_changes_and_states_in_effective_order(conn, tmp_path):
    wid = setup(conn, tmp_path)
    v1 = doc(("a1", "목적", "이 규정은 여비를 정한다."), ("a2", "정의", "여비란 운임이다."), ("a3", "기타", "따른다."))
    v2 = doc(("a1", "목적", "이 규정은 여비를 정한다."), ("a2", "정의", "여비란 운임과 일비이다."),
             ("a4", "기타", "따른다."))
    v3 = doc(("a1", "목적", "이 규정은 여비를 정한다."), ("a2", "정의", "여비란 운임과 일비이다."))
    # 도착 순서가 시행일 순서와 다르다 (Review Focus 5)
    id3 = add_version(conn, wid, src(conn, tmp_path, b"3"), v3, eff(date(2030, 1, 1)))
    id1 = add_version(conn, wid, src(conn, tmp_path, b"1"), v1, eff(date(2020, 1, 1)))
    id2 = add_version(conn, wid, src(conn, tmp_path, b"2"), v2, eff(date(2024, 1, 17)))
    st = rebuild_work(conn, wid, today=date(2026, 10, 2))
    assert st["versions"] == 3
    rows = {r["id"]: r for r in conn.execute(
        "SELECT id, version_state, effective_to FROM regulation.work_version WHERE work_id=%s", (wid,)).fetchall()}
    assert rows[id1]["version_state"] == "HISTORICAL" and rows[id1]["effective_to"] == date(2024, 1, 17)
    assert rows[id2]["version_state"] == "CURRENT" and rows[id3]["version_state"] == "FUTURE"
    assert changes(conn, wid, id2) == [("MODIFIED", "a2"), ("RENUMBERED", "a4")]
    assert changes(conn, wid, id3) == [("DELETED", "a4")]
    # 변경 없는 a1은 세 버전이 같은 provision_version 행을 공유
    n = conn.execute("SELECT count(DISTINCT pv.id) AS n FROM regulation.provision_version pv"
                     " JOIN regulation.provision p ON p.id = pv.provision_id WHERE p.work_id=%s AND pv.path='a1'",
                     (wid,)).fetchone()["n"]
    assert n == 1


def test_annotation_only_change(conn, tmp_path):
    wid = setup(conn, tmp_path)
    a = doc(("a1", "목적", "이 규정은 여비를 정한다."))
    b = doc(("a1", "목적", "이 규정은 여비를 정한다."))
    b.provisions[0].annotations = ["<개정 2024.1.17.>"]
    add_version(conn, wid, src(conn, tmp_path, b"a"), a, eff(date(2020, 1, 1)))
    vb = add_version(conn, wid, src(conn, tmp_path, b"b"), b, eff(date(2024, 1, 1)))
    rebuild_work(conn, wid, today=date(2026, 10, 2))
    assert changes(conn, wid, vb) == [("ANNOTATION_ONLY", "a1")]


def test_add_version_is_idempotent(conn, tmp_path):
    wid = setup(conn, tmp_path)
    sid = src(conn, tmp_path, b"x")
    d = doc(("a1", "목적", "x"))
    assert add_version(conn, wid, sid, d, eff(date(2020, 1, 1))) == add_version(conn, wid, sid, d, eff(date(2020, 1, 1)))
```

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_loader.py -q` → FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: 구현**

```python
# src/reg/load/__init__.py
```

```python
# src/reg/load/loader.py
"""work·버전 적재와 조항 계보 재구성 (world_law_collect loader 방식 이식, 시행일 순서 재계산)."""
import hashlib
import json
import re
from datetime import date

from reg.structure.effective import Effective
from reg.structure.model import ParsedDoc, Prov

_NORM = re.compile(r"[\s·ㆍ‧∙・]")
RENUMBER_UNITS = {"article", "paragraph", "item"}


def norm_title(s: str) -> str:
    return _NORM.sub("", s or "")


def text_hash(p: Prov) -> str:
    return hashlib.sha256(_NORM.sub("", (p.heading or "") + "|" + p.text).encode()).hexdigest()[:32]


def work_key_for_regulation(conn, inst_code: str, inst_id: int, title: str, seq: str) -> str:
    row = conn.execute("SELECT id FROM regulation.work WHERE external_ids->>'alio_seq' = %s", (seq,)).fetchone()
    if row:
        return row["id"]
    key = f"kr/reg/{inst_code}/{norm_title(title)}"
    taken = conn.execute("SELECT 1 FROM regulation.work WHERE id = %s", (key,)).fetchone()
    return f"{key}~{seq}" if taken else key


def upsert_work(conn, work_id: str, kind: str, title: str, institution_id: int | None, external_ids: dict) -> None:
    conn.execute(
        "INSERT INTO regulation.work (id, kind, title, institution_id, external_ids) VALUES (%s,%s,%s,%s,%s)"
        " ON CONFLICT (id) DO UPDATE SET title = EXCLUDED.title, external_ids = regulation.work.external_ids || EXCLUDED.external_ids",
        (work_id, kind, title, institution_id, json.dumps(external_ids, ensure_ascii=False)))


def add_version(conn, work_id: str, source_document_id: int, doc: ParsedDoc, eff: Effective,
                posted_on: date | None = None) -> str:
    row = conn.execute("SELECT id FROM regulation.work_version WHERE work_id = %s AND source_document_id = %s",
                       (work_id, source_document_id)).fetchone()
    if row:
        return row["id"]
    base = f"{work_id}@{eff.effective_from.isoformat()}" if eff.effective_from else f"{work_id}@undated-{source_document_id}"
    vid, n = base, 1
    while conn.execute("SELECT 1 FROM regulation.work_version WHERE id = %s", (vid,)).fetchone():
        n += 1
        vid = f"{base}.{n}"
    for p in doc.provisions:
        if p.unit == "article" and p.path in eff.overrides and p.effective_override is None:
            p.effective_override = eff.overrides[p.path]
    last = doc.history[-1] if doc.history else None
    conn.execute(
        "INSERT INTO regulation.work_version (id, work_id, source_document_id, title, promulgated_on, posted_on,"
        " effective_from, effective_basis, effective_status, amendment_kind, amendment_no, class_code, parsed,"
        " parse_stats) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (vid, work_id, source_document_id, doc.title or work_id, eff.promulgated_on, posted_on, eff.effective_from,
         eff.basis, eff.status, doc.meta.get("amendment_kind") or (last.kind if last else None),
         doc.meta.get("promulgation_no") or (last.number if last else None), doc.class_code,
         json.dumps(doc.to_json(), ensure_ascii=False), json.dumps(doc.meta.get("stats", {}))))
    for i, h in enumerate(doc.history):
        conn.execute("INSERT INTO regulation.amendment_history (work_version_id, ord, kind, date, number)"
                     " VALUES (%s,%s,%s,%s,%s)", (vid, i, h.kind, h.date, h.number))
    return vid


def _insert_pv(conn, prov_id: int, p: Prov) -> int:
    return conn.execute(
        "INSERT INTO regulation.provision_version (provision_id, path, unit, number_label, heading, parent_path, text,"
        " text_norm_hash, annotations, deleted, effective_from_override, source_anchor, meta)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (prov_id, p.path, p.unit, p.label, p.heading, p.parent, p.text, text_hash(p),
         json.dumps(p.annotations, ensure_ascii=False), p.deleted, p.effective_override,
         json.dumps(p.anchor) if p.anchor else None, json.dumps(p.meta, ensure_ascii=False))).fetchone()["id"]


def _new_provision(conn, work_id: str, key: str) -> int:
    return conn.execute("INSERT INTO regulation.provision (work_id, lineage_key) VALUES (%s,%s) RETURNING id",
                        (work_id, key)).fetchone()["id"]


def _change(conn, work_id, frm, to, prov_id, from_pv, to_pv, kind) -> None:
    conn.execute("INSERT INTO regulation.provision_change (work_id, from_version_id, to_version_id, provision_id,"
                 " from_pv_id, to_pv_id, kind) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                 (work_id, frm, to, prov_id, from_pv, to_pv, kind))


def rebuild_work(conn, work_id: str, today: date) -> dict:
    conn.execute("DELETE FROM regulation.provision_change WHERE work_id = %s", (work_id,))
    conn.execute("DELETE FROM regulation.version_provision WHERE work_version_id IN"
                 " (SELECT id FROM regulation.work_version WHERE work_id = %s)", (work_id,))
    conn.execute("DELETE FROM regulation.provision WHERE work_id = %s", (work_id,))
    versions = conn.execute(
        "SELECT id, effective_from, parsed FROM regulation.work_version WHERE work_id = %s"
        " ORDER BY effective_from NULLS LAST, created_at, id", (work_id,)).fetchall()
    dated = [v for v in versions if v["effective_from"]]
    for i, v in enumerate(versions):
        nxt = dated[dated.index(v) + 1]["effective_from"] if v in dated and dated.index(v) + 1 < len(dated) else None
        if v["effective_from"] is None:
            state = "UNDATED"
        elif v["effective_from"] > today:
            state = "FUTURE"
        elif nxt is None or nxt > today:
            state = "CURRENT"
        else:
            state = "HISTORICAL"
        conn.execute("UPDATE regulation.work_version SET effective_to = %s, version_state = %s WHERE id = %s",
                     (nxt, state, v["id"]))

    prev: dict[str, tuple[int, int, Prov]] | None = None  # path -> (provision_id, pv_id, Prov)
    prev_vid = None
    n_changes = 0
    for v in versions:
        doc = ParsedDoc.from_json(v["parsed"])
        cur: dict[str, tuple[int, int, Prov]] = {}
        base = prev if v["effective_from"] else None
        unmatched_prev = dict(base) if base else {}
        pending = []
        for ord_, p in enumerate(doc.provisions):
            if base is not None and p.path in base:
                pid, pvid, old = unmatched_prev.pop(p.path)
                pending.append((ord_, p, pid, pvid, old))
            else:
                pending.append((ord_, p, None, None, None))
        by_hash = {}
        for path, (pid, pvid, old) in unmatched_prev.items():
            if old.unit in RENUMBER_UNITS:
                by_hash.setdefault(text_hash(old), []).append(path)
        for ord_, p, pid, pvid, old in pending:
            kind = None
            if pid is None and base is not None and p.unit in RENUMBER_UNITS and by_hash.get(text_hash(p)):
                old_path = by_hash[text_hash(p)].pop(0)
                pid, pvid, old = unmatched_prev.pop(old_path)
                kind = "RENUMBERED"
            if pid is None:
                pid = _new_provision(conn, work_id, f"{p.path}@{v['id']}")
                new_pv = _insert_pv(conn, pid, p)
                if base is not None:
                    _change(conn, work_id, prev_vid, v["id"], pid, None, new_pv, "ADDED")
                    n_changes += 1
            else:
                same_text = text_hash(old) == text_hash(p) and old.heading == p.heading and old.deleted == p.deleted
                if kind is None and same_text and old.annotations == p.annotations and old.anchor == p.anchor \
                        and old.effective_override == p.effective_override:
                    new_pv = pvid
                else:
                    new_pv = _insert_pv(conn, pid, p)
                    kind = kind or ("ANNOTATION_ONLY" if same_text else "MODIFIED")
                if kind:
                    _change(conn, work_id, prev_vid, v["id"], pid, pvid, new_pv, kind)
                    n_changes += 1
            conn.execute("INSERT INTO regulation.version_provision (work_version_id, provision_version_id, ord)"
                         " VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", (v["id"], new_pv, ord_))
            cur[p.path] = (pid, new_pv, p)
        for path, (pid, pvid, old) in unmatched_prev.items():
            _change(conn, work_id, prev_vid, v["id"], pid, pvid, None, "DELETED")
            n_changes += 1
        if v["effective_from"]:
            prev, prev_vid = cur, v["id"]
    n_prov = conn.execute("SELECT count(*) AS n FROM regulation.provision WHERE work_id = %s",
                          (work_id,)).fetchone()["n"]
    return {"versions": len(versions), "provisions": n_prov, "changes": n_changes}
```

변경 이력의 `to_pv_id`는 `DELETED`일 때 NULL이다. 그런데 Task 1의 스키마는 `to_version_id`만 NOT NULL로 정하고 `to_pv_id`는 NULL을 허용하므로 그대로 맞는다.

- [ ] **Step 4: 통과 확인 후 커밋**

Run: `uv run pytest tests/test_loader.py -q` → 4 PASS

```bash
git add src/reg/load tests/test_loader.py
git commit -m "feat(load): work/version loader with lineage, change kinds and version states"
```

---

### Task 7: outbox 처리기와 CLI

**Files:**
- Create: `src/reg/process.py`, `tests/test_process.py`
- Modify: `src/reg/cli.py` (`reg process` 명령 추가)

**Interfaces:**
- Consumes: M1의 `source_document`, `alio_rule`, `alio_rule_file`, `institution`, `law_watch`와 이 계획의 Task 2~6
- Produces:
  - `process_once(conn, blob: BlobStore, limit: int = 100, today: date | None = None) -> dict`
    - 반환값: `{"claimed", "ok", "failed", "parked"}`
  - `handle_source_fetched(conn, blob, payload, today) -> str`: work_id를 돌려준다.
  - `handle_law_fetched(conn, blob, payload, today) -> str`
  - CLI `reg process [--limit N] [--all]`
    - `--all`이면 남은 이벤트가 없을 때까지 반복한다.
    - 실행은 M1과 같은 `_run("process", …)` 틀을 쓴다.
- 처리 규칙
  - 이벤트마다 savepoint를 하나씩 둔다.
    - 실패하면 그 savepoint까지 되돌린다.
    - 별도 문장으로 `attempts`를 1 늘리고 `last_error`를 기록한다.
    - 전체 배치 트랜잭션은 끝에 한 번 커밋한다.
  - ALIO 파일 처리
    - `alio_date`는 이 파일이 그 규정 `bFiles`의 마지막(`ord` 최대)일 때만 `alio_rule.revised_on`을 쓴다.
    - `posted_on`은 `alio_rule.posted_on`을 쓴다.
    - work 종류는 `INTERNAL_REG`다.
  - 법령 처리
    - work id는 `kr/law/{law_id}`다.
    - work 종류는 meta의 `kind`(법률·대통령령 등)를 쓴다. 없으면 `LAW`다.
    - `external_ids`는 `{"law_id", "mst"}`다.

- [ ] **Step 1: 실패하는 테스트**

```python
# tests/test_process.py
import json
from datetime import date
from pathlib import Path

from reg.collect.archive import store
from reg.collect.sniff import FileKind
from reg.process import process_once
from reg.storage.blob import LocalBlobStore

FX = Path(__file__).parent / "fixtures"
TODAY = date(2026, 10, 2)


def seed_alio(conn, blob, content: bytes, file_name="여비규정(2024년도 1월 개정).pdf", ord_=0):
    conn.execute("INSERT INTO regulation.institution (code, name, kind, alio_apba_id, alio_name)"
                 " VALUES ('KASI','한국천문연구원','GRI','C0266','한국천문연구원') ON CONFLICT DO NOTHING")
    inst = conn.execute("SELECT id FROM regulation.institution WHERE code='KASI'").fetchone()["id"]
    conn.execute("INSERT INTO regulation.alio_rule (seq, institution_id, title, revised_on, posted_on)"
                 " VALUES ('186618', %s, '여비규정', '2024-01-17', '2016-10-17') ON CONFLICT DO NOTHING", (inst,))
    doc = store(conn, blob, source="alio", url="u", content=content, kind=FileKind("application/pdf", "pdf"),
                meta={})
    conn.execute("INSERT INTO regulation.alio_rule_file (file_no, seq, file_name, ord, status, source_document_id)"
                 " VALUES (%s,'186618',%s,%s,'fetched',%s)", (str(doc.id), file_name, ord_, doc.id))
    conn.execute("INSERT INTO regulation.outbox (topic, payload) VALUES ('regulation.source_fetched', %s)",
                 (json.dumps({"source": "alio", "source_document_id": doc.id, "institution_code": "KASI",
                              "seq": "186618", "file_no": str(doc.id), "file_name": file_name}),))
    conn.commit()


def test_alio_pdf_event_builds_current_version(conn, tmp_path):
    blob = LocalBlobStore(tmp_path)
    seed_alio(conn, blob, (FX / "samples" / "kasi-yeobi-339.pdf").read_bytes())
    st = process_once(conn, blob, today=TODAY)
    assert st == {"claimed": 1, "ok": 1, "failed": 0, "parked": 0}
    v = conn.execute("SELECT * FROM regulation.work_version").fetchone()
    assert v["work_id"] == "kr/reg/KASI/여비규정" and v["effective_from"] == date(2024, 1, 17)
    assert (v["effective_basis"], v["effective_status"], v["version_state"]) == ("supplement", "CONFIRMED", "CURRENT")
    t = conn.execute("SELECT pv.text FROM regulation.provision_version pv JOIN regulation.version_provision vp"
                     " ON vp.provision_version_id = pv.id WHERE vp.work_version_id = %s AND pv.path = 'a27.p1'",
                     (v["id"],)).fetchone()["text"]
    assert "7일 이내에" in t
    assert process_once(conn, blob, today=TODAY)["claimed"] == 0


def test_law_event(conn, tmp_path):
    blob = LocalBlobStore(tmp_path)
    doc = store(conn, blob, source="lawgo", url="u", content=(FX / "lawgo_service_283849.xml").read_bytes(),
                kind=FileKind("application/xml", "xml"), meta={})
    conn.execute("INSERT INTO regulation.outbox (topic, payload) VALUES ('regulation.law_fetched', %s)",
                 (json.dumps({"law_id": "013774", "mst": "283849", "name": "국가연구개발혁신법",
                              "source_document_id": doc.id}),))
    conn.commit()
    assert process_once(conn, blob, today=TODAY)["ok"] == 1
    w = conn.execute("SELECT * FROM regulation.work").fetchone()
    assert w["id"] == "kr/law/013774" and w["kind"] == "법률"
    v = conn.execute("SELECT * FROM regulation.work_version").fetchone()
    assert v["effective_from"] == date(2026, 9, 11) and v["version_state"] == "CURRENT"


def test_broken_file_fails_then_parks(conn, tmp_path):
    blob = LocalBlobStore(tmp_path)
    seed_alio(conn, blob, b"%PDF-1.4 broken")
    for _ in range(3):
        process_once(conn, blob, today=TODAY)
    ev = conn.execute("SELECT attempts, processed_at, last_error FROM regulation.outbox").fetchone()
    assert ev["attempts"] == 3 and ev["processed_at"] is None and ev["last_error"]
    assert process_once(conn, blob, today=TODAY)["claimed"] == 0
```

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_process.py -q` → FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: 구현**

```python
# src/reg/process.py
"""outbox 소비자: 수집 이벤트 → 추출 → 파싱 → 시행일 판정 → 적재."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from reg.extract import extract
from reg.load.loader import add_version, rebuild_work, upsert_work, work_key_for_regulation
from reg.storage.blob import BlobStore
from reg.structure.effective import resolve
from reg.structure.law_xml import parse_law_xml
from reg.structure.parse import parse_blocks

MAX_ATTEMPTS = 3
TOPICS = ("regulation.source_fetched", "regulation.law_fetched")


def kst_today() -> date:
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def handle_source_fetched(conn, blob: BlobStore, payload: dict, today: date) -> str:
    sd = conn.execute("SELECT * FROM regulation.source_document WHERE id = %s",
                      (payload["source_document_id"],)).fetchone()
    rule = conn.execute(
        "SELECT r.*, i.code AS inst_code FROM regulation.alio_rule r JOIN regulation.institution i"
        " ON i.id = r.institution_id WHERE r.seq = %s", (payload["seq"],)).fetchone()
    last_ord = conn.execute("SELECT max(ord) AS m FROM regulation.alio_rule_file WHERE seq = %s AND status='fetched'",
                            (payload["seq"],)).fetchone()["m"]
    this = conn.execute("SELECT ord FROM regulation.alio_rule_file WHERE file_no = %s",
                        (payload["file_no"],)).fetchone()
    doc = parse_blocks(extract(blob.get(sd["blob_key"]), sd["mime"], payload["file_name"]))
    if not any(p.unit == "article" for p in doc.provisions):
        raise ValueError(f"조문을 찾지 못함 (stats={doc.meta.get('stats')})")
    alio_date = rule["revised_on"] if this and this["ord"] == last_ord else None
    eff = resolve(doc, alio_date=alio_date, filename=payload["file_name"])
    wid = work_key_for_regulation(conn, rule["inst_code"], rule["institution_id"], rule["title"], rule["seq"])
    upsert_work(conn, wid, "INTERNAL_REG", rule["title"], rule["institution_id"], {"alio_seq": rule["seq"]})
    add_version(conn, wid, sd["id"], doc, eff, posted_on=rule["posted_on"])
    rebuild_work(conn, wid, today)
    return wid


def handle_law_fetched(conn, blob: BlobStore, payload: dict, today: date) -> str:
    sd = conn.execute("SELECT * FROM regulation.source_document WHERE id = %s",
                      (payload["source_document_id"],)).fetchone()
    doc = parse_law_xml(blob.get(sd["blob_key"]))
    wid = f"kr/law/{payload['law_id']}"
    upsert_work(conn, wid, doc.meta.get("kind") or "LAW", doc.title, None,
                {"law_id": payload["law_id"], "mst": payload["mst"]})
    add_version(conn, wid, sd["id"], doc, resolve(doc))
    rebuild_work(conn, wid, today)
    return wid


HANDLERS = {"regulation.source_fetched": handle_source_fetched, "regulation.law_fetched": handle_law_fetched}


def process_once(conn, blob: BlobStore, limit: int = 100, today: date | None = None) -> dict:
    today = today or kst_today()
    st = {"claimed": 0, "ok": 0, "failed": 0, "parked": 0}
    events = conn.execute(
        "SELECT id, topic, payload, attempts FROM regulation.outbox WHERE processed_at IS NULL AND attempts < %s"
        " AND topic = ANY(%s) ORDER BY id LIMIT %s FOR UPDATE SKIP LOCKED",
        (MAX_ATTEMPTS, list(TOPICS), limit)).fetchall()
    for ev in events:
        st["claimed"] += 1
        try:
            with conn.transaction():
                HANDLERS[ev["topic"]](conn, blob, ev["payload"], today)
                conn.execute("UPDATE regulation.outbox SET processed_at = now(), claimed_at = now(),"
                             " last_error = NULL WHERE id = %s", (ev["id"],))
            st["ok"] += 1
        except Exception as e:  # 이벤트 하나의 실패가 배치를 멈추지 않게
            conn.execute("UPDATE regulation.outbox SET attempts = attempts + 1, claimed_at = now(), last_error = %s"
                         " WHERE id = %s", (f"{type(e).__name__}: {e}"[:2000], ev["id"]))
            st["failed"] += 1
            if ev["attempts"] + 1 >= MAX_ATTEMPTS:
                st["parked"] += 1
    conn.commit()
    return st
```

`src/reg/cli.py`에 추가한다. import 구역에 `from reg.process import process_once`를 넣는다.

```python
@app.command("process")
def process_cmd(limit: int = typer.Option(100, help="한 번에 처리할 이벤트 수"),
                all_: bool = typer.Option(False, "--all", help="남은 이벤트가 없을 때까지 반복")) -> None:
    def body(conn, log):
        total = {"claimed": 0, "ok": 0, "failed": 0, "parked": 0}
        while True:
            st = process_once(conn, _blob(), limit=limit)
            for k in total:
                total[k] += st[k]
            if not all_ or st["claimed"] == 0 or st["ok"] == 0:
                return total
    _run("process", None, body)
```

- [ ] **Step 4: 통과 확인 후 커밋**

Run: `uv run pytest -q` → 전체 PASS

```bash
git add src/reg/process.py src/reg/cli.py tests/test_process.py
git commit -m "feat(process): outbox consumer that structures and loads collected documents"
```

---

### Task 8: 파일럿 4개 기관 전체 수집과 적재

**Files:**
- Modify: `README.md` (`reg process` 한 줄 추가)
- Create: `docs/reports/2026-10-02-m2a-pilot-load.md` (적재 결과 보고)

- [ ] **Step 1: 실제 인프라 마이그레이션과 전체 수집**

```bash
set -a; . ./.env; set +a
uv run reg db upgrade
uv run reg collect alio > .superpowers/sdd/m2a-collect.log 2>&1   # 4개 기관 전체, 요청 간격 1.5초 (수십 분)
uv run reg collect law
```

Expected: 마지막 줄이 `완료 (run N): {...}`이고, 4개 기관 모두 `rules_seen > 100`이다.

- [ ] **Step 2: 처리**

```bash
uv run reg process --all
```

Expected:
- `failed`가 처리된 이벤트의 5% 이하다.
- 실패한 이벤트는 다음 SQL로 원인별로 묶는다. `SELECT left(last_error,60), count(*) FROM regulation.outbox WHERE processed_at IS NULL GROUP BY 1`
- 그 결과를 Step 4 보고서에 적는다.

- [ ] **Step 3: 실데이터 확인 쿼리**

```bash
docker exec nais-postgres-1 psql -U nais -d nais -c "
select split_part(w.id,'/',3) inst, count(distinct w.id) works, count(*) versions,
       count(*) filter (where version_state='CURRENT') current,
       count(*) filter (where effective_status='CONFIRMED') confirmed,
       count(*) filter (where effective_status='CONFLICT') conflict
from regulation.work_version v join regulation.work w on w.id=v.work_id group by 1 order by 1;"
docker exec nais-postgres-1 psql -U nais -d nais -c "
select pv.path, left(pv.text,60) from regulation.provision_version pv
join regulation.version_provision vp on vp.provision_version_id=pv.id
join regulation.work_version v on v.id=vp.work_version_id
where v.work_id='kr/reg/KASI/여비규정' and v.version_state='CURRENT' and pv.path like 'a27%';"
```

Expected:
- 각 work마다 `CURRENT`는 최대 1개다.
- 천문연 여비규정의 현행 버전에서 `a27.p1`이 "출장자는 출장 종료일 다음 날을 기점으로 7일 이내에…"로 나온다.

- [ ] **Step 4: 보고서 작성과 커밋**

`docs/reports/2026-10-02-m2a-pilot-load.md`에는 Step 1~3의 실제 숫자를 표로 적는다.
- 기관별 규정·버전 수
- 시행일 상태 분포
- 처리 실패 유형 상위 5개
- 대표 조문 1건

추정치는 넣지 않는다.

```bash
git add README.md docs/reports/2026-10-02-m2a-pilot-load.md
git commit -m "docs: M2a pilot load report (NST, KASI, KIST, ETRI)"
```

---

## Self-Review 결과

**스펙 대응**

| 스펙 | 반영 위치 |
|---|---|
| 5.1 개념 | Task 2 모델 |
| 5.2 식별자 | Global Constraints, Task 6 |
| 5.3 테이블 | Task 1 |
| 6.2 추출 | Task 3 |
| 6.3 구조 파싱 | Task 3, 4 |
| 6.5 시행일 판정 | Task 5 |
| 6.6 버전 적재와 실질 변경 구분 | Task 6 |
| 7 outbox 소비 | Task 7 |

**M2b로 넘기는 항목**
- 6.4 참조 추출
- 6.5의 품질 검사(목차 대조, 글자 수 비율)와 검수 큐
- 6.2 보기용 PDF 변환과 HWP `source_anchor`
- 별표 표 구조화(`attachment`)

**타입 일치**
- `Effective.overrides`를 Task 6 `add_version`에서 조 경로 키로 소비한다.
- `ParsedDoc.to_json`과 `from_json`이 `work_version.parsed`에 쓰이고, Task 6에서 다시 읽힌다.
- `process_once`의 반환 키가 테스트, CLI, 보고서에서 같다.

**Review Focus**
- 1~4번은 Task 3의 실파일 테스트가 다룬다.
- 5번은 Task 6의 `test_versions_changes_and_states_in_effective_order`가 다룬다.
