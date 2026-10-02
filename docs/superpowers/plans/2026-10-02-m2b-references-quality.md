# M2b 보기용 PDF·참조·품질 검수 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** M2a가 적재한 규정·법령 버전에 다음 네 가지를 더한다.

1. **보기용 PDF와 조문 원문 위치**: 원문 대조 보기에 쓴다.
2. **조문 간 참조 관계** (관계 유형 6가지): 대상 해석과 미해석 표시를 포함한다.
3. **품질 검사와 검수 큐**: 결과는 `validation_status`로 남긴다.
4. **전체 재처리 명령**: 규칙을 바꾼 뒤 처음부터 다시 처리할 때 쓴다.

**Architecture:**
- **변환기**: `reg.views`의 `Converter` 인터페이스 뒤에 둔다. 운영에서는 `DockerConverter`가 `docker run nst-regulation/converter`로 LibreOffice와 H2Orestart를 실행한다. 테스트에서는 가짜 변환기를 쓴다.
- **원문 위치**: `reg.views.anchor.locate`가 보기용 PDF의 줄을 받아, 조문 머리말이 처음 나오는 위치를 조항마다 찾는다. 찾는 순서는 앞에서 뒤로만 진행한다.
- **참조**: `reg.refs`가 조항 본문에서 참조 후보를 찾아낸다. `reg.refs.resolve`가 같은 문서, 같은 기관 규정, 법령 이름으로 대상을 찾는다. 찾지 못한 법령 이름은 `law_seed`에 넣어 수집 대상이 되게 한다.
- **품질 검사**: `reg.quality.check`가 시행일 상태, 조 번호 공백, 목차와 본문 불일치를 검사하고 `review_task`를 만든다.
- **처리기 연결**: 처리기(`reg.process`)가 위 단계를 순서대로 호출한다.

**Tech Stack:** M2a 스택에 Docker 이미지 `nst-regulation/converter:0.1`(`infra/converter/Dockerfile`, LibreOffice 7.4 + H2Orestart v0.7.14)을 더한다.

**Spec:** `docs/superpowers/specs/2026-10-01-regulation-platform-design.md` (5.1 관계 유형, 5.3 reference·review_task, 6.2 보기용 PDF, 6.4 참조, 6.5 품질 검사, 10 원문 대조)

## Global Constraints

- **DB**: M1과 M2a의 제약을 그대로 따른다. 테이블은 `regulation.`에 둔다.
- **관계 유형**: `BASIS|DELEGATION|IMPLEMENTS|MUTATIS|EXCEPTION|CITATION`. 이번 단계에서 판정하는 것은 `IMPLEMENTS`를 뺀 5종이다. `IMPLEMENTS`는 위임 연결 단계(M5)에서 만든다.
- **target_kind**: `PROVISION|WORK|ANNEX|NONE|EXTERNAL_UNRESOLVED`
- **resolution**: `RESOLVED|AMBIGUOUS|UNRESOLVED`
- **review_task.kind**: `PARSE|EFFECTIVE_DATE|REFERENCE|CONFLICT|LOW_TEXT`
- **review_task.status**: `OPEN|RESOLVED|DISMISSED`
- **보기용 PDF 키**: `view/{원본 sha256}.pdf`
  - PDF 원본은 원본 키를 그대로 보기용으로 쓴다.
  - 변환에 실패하면 `source_document.view_status='failed'`로 남긴다. 이벤트 자체는 실패로 치지 않는다.
- **validation_status**: `PASSED|REVIEW`
  - `REVIEW`: 열린 검수 작업 중 종류가 `PARSE`, `CONFLICT`, `LOW_TEXT`인 것이 하나라도 있을 때
  - `EFFECTIVE_DATE`(시행일 불확실)와 `REFERENCE`(참조 미해석)만 있으면 `PASSED`로 두고, 작업은 검수 큐에만 남긴다.

## Review Focus

1. **"제13조의 근무지내 출장"처럼 조 번호 뒤에 "의"가 오는 경우.** "의" 뒤에 숫자가 없으면 제13조를 가리키는 참조여야 한다. 제13조의2로 읽으면 안 된다. Task 4에서 테스트한다.
2. **「국가공무원 복무·징계 관련 예규」처럼 수집 대상에 없는 행정규칙.** `UNRESOLVED`로 남기고 `law_seed`에 넣는다. 제목 끝이 예규·훈령·고시이므로 법령 후보로 판정되어야 한다. Task 4에서 테스트한다.
3. **변환기를 쓸 수 없는 경우**(Docker 없음, 시간 초과). 처리가 실패하지 않고 원문 위치만 비어야 한다. Task 3에서 테스트한다.
4. **목차가 없는 HWP 문서.** 목차 불일치 검사를 건너뛰고 오탐을 내지 않아야 한다. Task 5에서 테스트한다.
5. **같은 검수 작업이 반복 처리마다 쌓이는 경우.** `(kind, target)`이 같은 작업은 하나만 있어야 한다. Task 5에서 테스트한다.

---

## File Structure

```
infra/converter/Dockerfile            # (작성 완료) LibreOffice + H2Orestart
src/reg/views/__init__.py
src/reg/views/converter.py            # Converter, DockerConverter, ConversionError
src/reg/views/anchor.py               # locate(doc, blocks) -> int (붙인 개수)
src/reg/refs.py                       # RefCandidate, extract_refs(doc), resolve_and_store(conn, work_id, version_id)
src/reg/quality.py                    # Issue, check(doc, eff), record(conn, version_id, issues)
src/reg/migrations/versions/0003_refs_quality.py
src/reg/structure/parse.py            # (수정) meta["toc"] 기록
src/reg/process.py                    # (수정) 변환·위치·참조·품질 연결, rebuild_all
src/reg/collect/law_sync.py           # (수정) law_seed 이름 병합
src/reg/cli.py                        # (수정) process --rebuild, collect law가 law_seed 사용
tests/fixtures/samples/nst-yeobi-18.view.pdf   # 변환기로 만든 보기용 PDF (고정본)
tests/test_converter.py tests/test_anchor.py tests/test_refs.py tests/test_quality.py tests/test_process_m2b.py
```

---

### Task 1: 0003 마이그레이션

**Files:**
- Create: `src/reg/migrations/versions/0003_refs_quality.py`, `tests/test_migrations_0003.py`
- Modify: `tests/conftest.py`. TRUNCATE 목록 맨 앞에 `regulation.reference, regulation.review_task, regulation.law_seed,`를 추가한다.

**Interfaces:**
- Produces:
  - 새 컬럼
    - `source_document.view_blob_key text`
    - `source_document.view_status text` (`pending|ready|failed|not_needed`, 기본값 `pending`)
    - `work_version.validation_status text` (기본값 `PASSED`)
  - 새 테이블: `reference`, `review_task`, `law_seed`

- [ ] **Step 1: 실패하는 테스트**

```python
# tests/test_migrations_0003.py
def cols(conn, table):
    return {r["column_name"] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema='regulation' AND table_name=%s",
        (table,)).fetchall()}


def test_m2b_schema(conn):
    assert {"view_blob_key", "view_status"} <= cols(conn, "source_document")
    assert "validation_status" in cols(conn, "work_version")
    assert {"source_pv_id", "rel_type", "target_kind", "target_work_id", "target_path", "target_name",
            "resolution", "evidence_text"} <= cols(conn, "reference")
    assert {"kind", "target", "status", "detail"} <= cols(conn, "review_task")
    assert {"name", "origin"} <= cols(conn, "law_seed")
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_migrations_0003.py -q` → FAIL

- [ ] **Step 3: 구현**

```python
# src/reg/migrations/versions/0003_refs_quality.py
"""M2b 보기용 PDF·참조·검수"""
from alembic import op

revision = "0003"
down_revision = "0002"

DDL = """
ALTER TABLE regulation.source_document
  ADD COLUMN view_blob_key text,
  ADD COLUMN view_status text NOT NULL DEFAULT 'pending'
    CHECK (view_status IN ('pending', 'ready', 'failed', 'not_needed'));
ALTER TABLE regulation.work_version
  ADD COLUMN validation_status text NOT NULL DEFAULT 'PASSED' CHECK (validation_status IN ('PASSED', 'REVIEW'));
CREATE TABLE regulation.reference (
  id bigserial PRIMARY KEY,
  work_id text NOT NULL REFERENCES regulation.work(id),
  source_pv_id bigint NOT NULL REFERENCES regulation.provision_version(id) ON DELETE CASCADE,
  evidence_text text NOT NULL,
  span_start int NOT NULL,
  span_end int NOT NULL,
  rel_type text NOT NULL CHECK (rel_type IN ('BASIS', 'DELEGATION', 'IMPLEMENTS', 'MUTATIS', 'EXCEPTION', 'CITATION')),
  target_kind text NOT NULL CHECK (target_kind IN ('PROVISION', 'WORK', 'ANNEX', 'NONE', 'EXTERNAL_UNRESOLVED')),
  target_work_id text REFERENCES regulation.work(id),
  target_path text,
  target_name text,
  resolution text NOT NULL CHECK (resolution IN ('RESOLVED', 'AMBIGUOUS', 'UNRESOLVED')),
  confidence real NOT NULL DEFAULT 1.0,
  extractor text NOT NULL DEFAULT 'rule',
  review_status text NOT NULL DEFAULT 'AUTO' CHECK (review_status IN ('AUTO', 'PENDING', 'ACCEPTED', 'REJECTED'))
);
CREATE INDEX reference_source ON regulation.reference (source_pv_id);
CREATE INDEX reference_target ON regulation.reference (target_work_id, target_path);
CREATE TABLE regulation.review_task (
  id bigserial PRIMARY KEY,
  kind text NOT NULL CHECK (kind IN ('PARSE', 'EFFECTIVE_DATE', 'REFERENCE', 'CONFLICT', 'LOW_TEXT')),
  target text NOT NULL,
  work_id text REFERENCES regulation.work(id) ON DELETE CASCADE,
  detail jsonb NOT NULL DEFAULT '{}',
  status text NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'RESOLVED', 'DISMISSED')),
  assignee text,
  decision jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  resolved_at timestamptz,
  UNIQUE (kind, target)
);
CREATE TABLE regulation.law_seed (
  name text PRIMARY KEY,
  origin text NOT NULL CHECK (origin IN ('config', 'reference')),
  first_seen_work_id text,
  created_at timestamptz NOT NULL DEFAULT now()
);
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    op.execute("DROP TABLE regulation.law_seed; DROP TABLE regulation.review_task; DROP TABLE regulation.reference;"
               " ALTER TABLE regulation.work_version DROP COLUMN validation_status;"
               " ALTER TABLE regulation.source_document DROP COLUMN view_status, DROP COLUMN view_blob_key;")
```

- [ ] **Step 4: 통과 확인 후 커밋** — `uv run pytest -q` → 전체 PASS

```bash
git add src/reg/migrations/versions/0003_refs_quality.py tests/test_migrations_0003.py tests/conftest.py
git commit -m "feat(db): view pdf, references, review tasks, law seeds (0003)"
```

---

### Task 2: 변환기

**Files:**
- Create: `src/reg/views/__init__.py`, `src/reg/views/converter.py`, `tests/test_converter.py`, `infra/converter/Dockerfile`(이미 작성됨, 커밋에 포함), `tests/fixtures/samples/nst-yeobi-18.view.pdf`

**Interfaces:**
- Produces:
  - `class ConversionError(Exception)`
  - `class Converter(Protocol)`: `to_pdf(data: bytes, ext: str) -> bytes`
  - `DockerConverter(image: str = "nst-regulation/converter:0.1", timeout: float = 120.0)`
    - 임시 디렉터리에 `in.{ext}`를 쓴다.
    - `docker run --rm -u UID:GID -e HOME=/tmp --network none -v tmp:/work image /work/in.{ext}`로 변환한다.
    - `out/in.pdf`를 읽어 돌려준다.
    - 결과 파일이 없거나 `%PDF`로 시작하지 않거나 시간이 초과되면 `ConversionError`
- `--network none`: 변환기는 외부 접속이 필요 없다.

- [ ] **Step 1: 보기용 PDF 고정본 만들기와 실패하는 테스트**

```bash
docker build -t nst-regulation/converter:0.1 infra/converter
D=$(mktemp -d) && cp tests/fixtures/samples/nst-yeobi-18.hwp $D/in.hwp && \
  docker run --rm -u $(id -u):$(id -g) -e HOME=/tmp --network none -v $D:/work nst-regulation/converter:0.1 /work/in.hwp && \
  cp $D/out/in.pdf tests/fixtures/samples/nst-yeobi-18.view.pdf
```

```python
# tests/test_converter.py
from pathlib import Path

import pytest

from reg.views.converter import ConversionError, DockerConverter

S = Path(__file__).parent / "fixtures" / "samples"


@pytest.mark.integration
def test_docker_converter_hwp_to_pdf():
    pdf = DockerConverter().to_pdf((S / "nst-yeobi-18.hwp").read_bytes(), "hwp")
    assert pdf.startswith(b"%PDF") and len(pdf) > 50_000


def test_missing_image_raises_conversion_error():
    with pytest.raises(ConversionError):
        DockerConverter(image="nst-regulation/does-not-exist:0", timeout=60).to_pdf(b"x", "hwp")
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_converter.py -q` → FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: 구현**

```python
# src/reg/views/__init__.py
```

```python
# src/reg/views/converter.py
"""HWP·HWPX → 보기용 PDF. 운영: LibreOffice+H2Orestart 컨테이너 (infra/converter)."""
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Protocol


class ConversionError(Exception):
    pass


class Converter(Protocol):
    def to_pdf(self, data: bytes, ext: str) -> bytes: ...


class DockerConverter:
    def __init__(self, image: str = "nst-regulation/converter:0.1", timeout: float = 120.0):
        self.image, self.timeout = image, timeout

    def to_pdf(self, data: bytes, ext: str) -> bytes:
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / f"in.{ext}"
            src.write_bytes(data)
            os.chmod(d, 0o777)
            cmd = ["docker", "run", "--rm", "-u", f"{os.getuid()}:{os.getgid()}", "-e", "HOME=/tmp",
                   "--network", "none", "-v", f"{d}:/work", self.image, f"/work/in.{ext}"]
            try:
                r = subprocess.run(cmd, capture_output=True, timeout=self.timeout)
            except (subprocess.TimeoutExpired, FileNotFoundError) as e:
                raise ConversionError(f"변환기 실행 실패: {e!r}") from e
            out = Path(d) / "out" / "in.pdf"
            if r.returncode != 0 or not out.exists():
                raise ConversionError(f"변환 실패 (rc={r.returncode}): {r.stderr.decode(errors='replace')[-300:]}")
            pdf = out.read_bytes()
            if not pdf.startswith(b"%PDF"):
                raise ConversionError("변환 결과가 PDF가 아님")
            return pdf
```

- [ ] **Step 4: 통과 확인과 커밋**
  - `uv run pytest tests/test_converter.py -q` → 1 PASS
  - `uv run pytest -m integration tests/test_converter.py -q` → 1 PASS

```bash
git add infra/converter/Dockerfile src/reg/views tests/test_converter.py tests/fixtures/samples/nst-yeobi-18.view.pdf
git commit -m "feat(views): HWP to PDF converter (LibreOffice + H2Orestart container)"
```

---

### Task 3: 원문 위치(anchor)

**Files:**
- Create: `src/reg/views/anchor.py`, `tests/test_anchor.py`

**Interfaces:**
- Produces: `locate(doc: ParsedDoc, blocks: list[Block]) -> int`
  - 대상 단위는 `chapter`, `article`, `paragraph`, `item`, `supplement`, `annex`다.
  - 조항마다 "검색 키" 앞부분(공백을 뺀 앞 12자)을 정한다.
    - 장: `제N장`
    - 조: `제N조` 또는 `제N조의K`와, 제목이 있으면 `(제목`
    - 항: 원문자 + 본문 앞 8자
    - 호: `N.` + 본문 앞 8자
    - 부칙: `부칙`
    - 별표: `별표제N호`
  - 블록 텍스트도 공백을 뺀 형태로 바꿔서, **앞 위치에서부터만** 검색 키로 시작하는 줄을 찾는다. 이렇게 하면 목차에 같은 글자가 있어도 본문 순서대로 맞춰진다.
  - 찾으면 `anchor = {"page", "bbox"}`를 넣는다.
  - 이미 `anchor`가 있는 조항(PDF 원본)은 건드리지 않는다.
  - 붙인 개수를 돌려준다.

- [ ] **Step 1: 실패하는 테스트**

```python
# tests/test_anchor.py
from pathlib import Path

from reg.extract import extract
from reg.extract.pdf import extract_pdf
from reg.structure.parse import parse_blocks
from reg.views.anchor import locate

S = Path(__file__).parent / "fixtures" / "samples"


def test_hwp_provisions_get_anchors_from_view_pdf():
    doc = parse_blocks(extract((S / "nst-yeobi-18.hwp").read_bytes(), "application/x-hwp", "a.hwp"))
    n = locate(doc, extract_pdf((S / "nst-yeobi-18.view.pdf").read_bytes()))
    a = doc.get("a9-2")
    assert a.anchor and a.anchor["page"] == 5 and len(a.anchor["bbox"]) == 4
    assert doc.get("a1").anchor["page"] == 2
    arts = [p for p in doc.provisions if p.unit == "article"]
    assert sum(1 for p in arts if p.anchor) / len(arts) > 0.9 and n > len(arts)
    pages = [p.anchor["page"] for p in arts if p.anchor]
    assert pages == sorted(pages)  # 본문 순서대로
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_anchor.py -q` → FAIL

- [ ] **Step 3: 구현**

```python
# src/reg/views/anchor.py
"""보기용 PDF 줄에서 조항 위치 찾기 (공백 무시, 문서 순서대로 전진 검색)."""
import re

from reg.structure.model import Block, ParsedDoc, Prov

_WS = re.compile(r"\s+")
UNITS = {"chapter", "article", "paragraph", "item", "supplement", "annex"}


def _n(s: str) -> str:
    return _WS.sub("", s or "")


def _key(p: Prov) -> str | None:
    if p.unit == "chapter":
        return _n(p.label)
    if p.unit == "article":
        return _n(p.label + (f"({p.heading}" if p.heading else ""))[:12]
    if p.unit in ("paragraph", "item"):
        return _n(p.label + p.text)[:10]
    if p.unit == "supplement":
        return "부칙"
    if p.unit == "annex":
        return _n(p.label)
    return None


def locate(doc: ParsedDoc, blocks: list[Block]) -> int:
    lines = [_n(b.text) for b in blocks]
    pos, n = 0, 0
    for p in doc.provisions:
        if p.unit not in UNITS or p.anchor:
            continue
        key = _key(p)
        if not key:
            continue
        for i in range(pos, len(lines)):
            if lines[i].startswith(key) or (p.unit in ("paragraph", "item") and key in lines[i]):
                b = blocks[i]
                p.anchor = {"page": b.page, "bbox": list(b.bbox) if b.bbox else None}
                pos, n = i, n + 1
                break
    return n
```

- [ ] **Step 4: 통과 확인 후 커밋** — `uv run pytest tests/test_anchor.py -q` → PASS

```bash
git add src/reg/views/anchor.py tests/test_anchor.py
git commit -m "feat(views): locate provisions in the view PDF"
```

---

### Task 4: 참조 추출과 해석

**Files:**
- Create: `src/reg/refs.py`, `tests/test_refs.py`
- Modify: `src/reg/collect/law_sync.py`, `src/reg/cli.py`. `collect law`가 `config/laws.yaml`과 `law_seed`의 이름을 합쳐서 쓰도록 바꾼다.

**Interfaces:**
- Produces:
  - `RefCandidate(path: str, start: int, end: int, evidence: str, rel_type: str, kind: str, name: str | None, target_path: str | None)` (dataclass)
    - `kind` ∈ `internal|external|annex|delegation`
  - `extract_refs(p: Prov) -> list[RefCandidate]`
    - 관계 유형 판정
      - 참조 뒤 30자 안에 "준용"이 있으면 `MUTATIS`
      - 참조 바로 뒤가 "에도 불구하고"면 `EXCEPTION`
      - 외부 법령이고 "에 따라|에 의하여|에 근거하여"면 `BASIS`
      - 그 밖에는 `CITATION`
    - 상대 참조
      - "전항"은 같은 조의 직전 항이다.
      - "같은 조"·"이 조"는 현재 조다.
      - "제N항"은 같은 조의 N항이다.
    - "따로 정한다"·"별도로 정한다"는 대상 없는 `DELEGATION`이다.
  - `looks_like_law(name: str) -> bool`: 이름 끝이 `법|법률|령|규칙|규정|예규|훈령|고시|지침|기준`이면 참이다.
  - `resolve_and_store(conn, work_id: str) -> dict`
    - 그 work의 모든 provision_version에 대해 참조를 다시 만든다. 기존 것은 지운다.
    - 대상 해석
      - 내부 참조: 같은 work에서 경로가 있는지 본다.
      - 외부 참조: 법령(`kr/law/*`)과 같은 기관 규정을 제목 정규화(`norm_title`)로 비교한다.
    - 미해석 외부 이름 중 `looks_like_law`가 참이면 `law_seed(origin='reference')`에 넣는다.
    - 반환값: `{"refs", "resolved", "unresolved", "seeds"}`

- [ ] **Step 1: 실패하는 테스트**

```python
# tests/test_refs.py
from datetime import date

from reg.collect.archive import store
from reg.collect.sniff import FileKind
from reg.load.loader import add_version, rebuild_work, upsert_work
from reg.refs import extract_refs, looks_like_law, resolve_and_store
from reg.storage.blob import LocalBlobStore
from reg.structure.effective import Effective
from reg.structure.model import ParsedDoc, Prov


def P(path, text, unit="paragraph", label="③", heading=None, parent="a27"):
    return Prov(path, unit, label, heading, text, parent)


def test_exception_and_article_ref_with_trailing_ui():
    refs = extract_refs(P("a27.p3", "제1항에도 불구하고 제13조의 근무지내 출장의 경우는 증빙서 제출을 생략할 수 있다."))
    got = [(r.kind, r.target_path, r.rel_type) for r in refs]
    assert ("internal", "a27.p1", "EXCEPTION") in got
    assert ("internal", "a13", "CITATION") in got


def test_branch_article_and_item():
    refs = extract_refs(P("a6-2.p1", "「여신전문금융업법」제2조 제3호에 따른 신용카드"))
    r = refs[0]
    assert (r.kind, r.name, r.target_path, r.rel_type) == ("external", "여신전문금융업법", "a2.i3", "BASIS")
    refs2 = extract_refs(P("a3.p1", "제7조의2제1항을 준용한다."))
    assert [(x.kind, x.target_path, x.rel_type) for x in refs2] == [("internal", "a7-2.p1", "MUTATIS")]


def test_mutatis_external_names_and_previous_paragraph():
    refs = extract_refs(P("a29", "이 규정에서 정하지 아니한 사항은 「공무원 여비규정」 및 「국가공무원 복무·징계 관련 예규」를"
                                 " 준용할 수 있다.", unit="article", label="제29조", heading="기타", parent=None))
    assert [(r.name, r.rel_type) for r in refs] == [("공무원 여비규정", "MUTATIS"),
                                                     ("국가공무원 복무·징계 관련 예규", "MUTATIS")]
    prev = extract_refs(P("a10.p2", "전항의 숙박비는 실비로 지급한다.", parent="a10"))
    assert [(r.kind, r.target_path) for r in prev] == [("internal", "a10.p1")]


def test_annex_and_delegation():
    refs = extract_refs(P("a9", "국내출장에 있어서 여비는 별표 1에 정하는 바에 의하여 지급하고, 세부사항은 원장이 따로 정한다.",
                          unit="article", label="제9조", parent=None))
    assert ("annex", "annex1") in [(r.kind, r.target_path) for r in refs]
    assert any(r.kind == "delegation" and r.rel_type == "DELEGATION" for r in refs)


def test_looks_like_law():
    assert looks_like_law("국가공무원 복무·징계 관련 예규") and looks_like_law("공무원 여비 규정")
    assert not looks_like_law("방문기관확인서")


def _load(conn, tmp_path, wid, kind, title, provs, inst=None, tag=b""):
    upsert_work(conn, wid, kind, title, inst, {})
    sid = store(conn, LocalBlobStore(tmp_path), source="alio", url="u", content=b"%PDF" + wid.encode() + tag,
                kind=FileKind("application/pdf", "pdf"), meta={}).id
    add_version(conn, wid, sid, ParsedDoc(title, None, [], provs), Effective(date(2024, 1, 1), "api", "CONFIRMED", None))
    rebuild_work(conn, wid, date(2026, 10, 2))


def test_resolve_against_laws_and_seed_unknown(conn, tmp_path):
    inst = conn.execute("INSERT INTO regulation.institution (code, name, kind) VALUES ('KASI','천문연','GRI')"
                        " RETURNING id").fetchone()["id"]
    _load(conn, tmp_path, "kr/law/000001", "대통령령", "공무원 여비 규정", [Prov("a1", "article", "제1조", "목적", "x")])
    _load(conn, tmp_path, "kr/reg/KASI/여비규정", "INTERNAL_REG", "여비규정", [
        Prov("a13", "article", "제13조", "근무지내 출장", "근무지내 출장은"),
        Prov("a29", "article", "제29조", "기타", "이 규정에서 정하지 아니한 사항은 「공무원 여비규정」 및 "
             "「국가공무원 복무·징계 관련 예규」를 준용할 수 있다."),
        Prov("a30", "article", "제30조", "적용", "제13조에 따른다.")], inst)
    st = resolve_and_store(conn, "kr/reg/KASI/여비규정")
    rows = conn.execute("SELECT target_name, target_work_id, target_path, resolution, rel_type FROM regulation.reference"
                        " WHERE work_id='kr/reg/KASI/여비규정' ORDER BY id").fetchall()
    by = {(r["target_name"] or r["target_path"]): r for r in rows}
    assert by["공무원 여비규정"]["target_work_id"] == "kr/law/000001" and by["공무원 여비규정"]["resolution"] == "RESOLVED"
    assert by["국가공무원 복무·징계 관련 예규"]["resolution"] == "UNRESOLVED"
    assert by["a13"]["resolution"] == "RESOLVED" and by["a13"]["target_work_id"] == "kr/reg/KASI/여비규정"
    seed = conn.execute("SELECT origin FROM regulation.law_seed WHERE name='국가공무원 복무·징계 관련 예규'").fetchone()
    assert seed["origin"] == "reference" and st["seeds"] == 1
    assert resolve_and_store(conn, "kr/reg/KASI/여비규정")["refs"] == st["refs"]  # 다시 해도 중복 없음
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_refs.py -q` → FAIL

- [ ] **Step 3: 구현**

```python
# src/reg/refs.py
"""조문 본문의 참조 추출(규칙 기반)과 대상 해석 (spec 6.4)."""
import re
from dataclasses import dataclass

from reg.load.loader import norm_title
from reg.structure.model import Prov

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
RE_NAME = re.compile(r"「\s*([^」]{2,80}?)\s*」")
RE_ART = re.compile(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+)(?!\d))?(?:\s*제\s*(\d+)\s*항)?(?:\s*제\s*(\d+)\s*호)?"
                    r"(?:\s*([가-하])\s*목)?")
RE_PARA_ONLY = re.compile(r"(?<![조\d])\s?제\s*(\d+)\s*항|전\s*항|같은\s*조|이\s*조")
RE_ANNEX = re.compile(r"(별\s*표|별\s*지)\s*(?:제\s*)?(\d+)\s*(?:호)?(?:\s*의\s*(\d+))?")
RE_DELEG = re.compile(r"(?:따로|별도로)\s*정한다|(?:으)?로\s*정하는\s*바에\s*따른다")
LAW_TAIL = re.compile(r"(법|법률|령|규칙|규정|예규|훈령|고시|지침|기준)$")


@dataclass
class RefCandidate:
    path: str
    start: int
    end: int
    evidence: str
    rel_type: str
    kind: str
    name: str | None
    target_path: str | None


def looks_like_law(name: str) -> bool:
    return bool(LAW_TAIL.search(norm_title(name)))


def _art_path(m) -> str:
    p = f"a{int(m[1])}" + (f"-{int(m[2])}" if m[2] else "")
    if m[3]:
        p += f".p{int(m[3])}"
    if m[4]:
        p += f".i{int(m[4])}"
    if m[5]:
        p += f".s{m[5]}"
    return p


def _rel(text: str, end: int, external: bool) -> str:
    after = text[end:end + 30]
    if re.match(r"\s*(?:의\s*규정)?\s*에도\s*불구하고", after):
        return "EXCEPTION"
    if "준용" in after.split("다.")[0]:
        return "MUTATIS"
    if external and re.match(r"\s*(?:의\s*규정)?\s*에\s*(?:따라|따른|의하여|의한|근거하여|근거한)", after):
        return "BASIS"
    return "CITATION"


def _article_of(path: str) -> str:
    return path.split(".")[0].split("/")[-1] if "/" not in path else path.split(".")[0]


def extract_refs(p: Prov) -> list[RefCandidate]:
    text, out, taken = p.text or "", [], []

    def free(s, e):
        return all(e <= a or s >= b for a, b in taken)

    for m in RE_NAME.finditer(text):
        end = m.end()
        art = RE_ART.match(text, end) or RE_ART.match(text, end + 1)
        if art and art.start() - end <= 1:
            end = art.end()
        out.append(RefCandidate(p.path, m.start(), end, text[m.start():end], _rel(text, end, True), "external",
                                m[1].strip(), _art_path(art) if art and art.start() - m.end() <= 1 else None))
        taken.append((m.start(), end))
    for m in RE_ART.finditer(text):
        if not free(m.start(), m.end()):
            continue
        out.append(RefCandidate(p.path, m.start(), m.end(), m[0], _rel(text, m.end(), False), "internal", None,
                                _art_path(m)))
        taken.append((m.start(), m.end()))
    art = _article_of(p.path)
    for m in RE_PARA_ONLY.finditer(text):
        s = m.start() + (1 if m[0][:1].isspace() else 0)
        if not free(s, m.end()):
            continue
        tok = m[0].strip()
        if m[1]:
            target = f"{art}.p{int(m[1])}"
        elif tok.startswith("전"):
            cur = re.search(r"\.p(\d+)", p.path)
            if not cur or int(cur[1]) < 2:
                continue
            target = f"{art}.p{int(cur[1]) - 1}"
        else:
            target = art
        out.append(RefCandidate(p.path, s, m.end(), tok, _rel(text, m.end(), False), "internal", None, target))
        taken.append((s, m.end()))
    for m in RE_ANNEX.finditer(text):
        if not free(m.start(), m.end()):
            continue
        kind = "annex" if "표" in m[1] else "form"
        target = f"{kind}{int(m[2])}" + (f"-{int(m[3])}" if m[3] else "")
        out.append(RefCandidate(p.path, m.start(), m.end(), m[0], "CITATION", "annex", None, target))
        taken.append((m.start(), m.end()))
    for m in RE_DELEG.finditer(text):
        out.append(RefCandidate(p.path, m.start(), m.end(), m[0], "DELEGATION", "delegation", None, None))
    return sorted(out, key=lambda r: r.start)


def resolve_and_store(conn, work_id: str) -> dict:
    conn.execute("DELETE FROM regulation.reference WHERE work_id = %s", (work_id,))
    work = conn.execute("SELECT * FROM regulation.work WHERE id = %s", (work_id,)).fetchone()
    titles = {}
    for w in conn.execute("SELECT id, title FROM regulation.work WHERE id LIKE 'kr/law/%%' OR institution_id = %s",
                          (work["institution_id"],)).fetchall():
        titles.setdefault(norm_title(w["title"]), []).append(w["id"])
    pvs = conn.execute(
        "SELECT DISTINCT pv.* FROM regulation.provision_version pv JOIN regulation.provision p ON p.id = pv.provision_id"
        " WHERE p.work_id = %s", (work_id,)).fetchall()
    paths = {pv["path"] for pv in pvs}
    st = {"refs": 0, "resolved": 0, "unresolved": 0, "seeds": 0}
    for pv in pvs:
        prov = Prov(pv["path"], pv["unit"], pv["number_label"], pv["heading"], pv["text"], pv["parent_path"])
        for r in extract_refs(prov):
            tw, tpath, kind, res = None, r.target_path, "NONE", "RESOLVED"
            if r.kind == "internal":
                tw, kind = work_id, "PROVISION"
                res = "RESOLVED" if tpath in paths or tpath.split(".")[0] in paths else "UNRESOLVED"
            elif r.kind == "annex":
                tw, kind = work_id, "ANNEX"
                res = "RESOLVED" if tpath in paths else "UNRESOLVED"
            elif r.kind == "external":
                hits = titles.get(norm_title(r.name), [])
                if len(hits) == 1:
                    tw, kind = hits[0], "PROVISION" if tpath else "WORK"
                elif len(hits) > 1:
                    kind, res = "EXTERNAL_UNRESOLVED", "AMBIGUOUS"
                else:
                    kind, res = "EXTERNAL_UNRESOLVED", "UNRESOLVED"
                    if looks_like_law(r.name):
                        cur = conn.execute("INSERT INTO regulation.law_seed (name, origin, first_seen_work_id)"
                                           " VALUES (%s, 'reference', %s) ON CONFLICT DO NOTHING", (r.name, work_id))
                        st["seeds"] += cur.rowcount
            conn.execute(
                "INSERT INTO regulation.reference (work_id, source_pv_id, evidence_text, span_start, span_end, rel_type,"
                " target_kind, target_work_id, target_path, target_name, resolution) VALUES"
                " (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (work_id, pv["id"], r.evidence, r.start, r.end, r.rel_type, kind, tw, tpath, r.name, res))
            st["refs"] += 1
            st["resolved" if res == "RESOLVED" else "unresolved"] += 1
    return st
```

`src/reg/collect/law_sync.py`는 바꾸지 않는다. `src/reg/cli.py`의 `collect_law`에서 이름 목록을 다음과 같이 합친다.

```python
        names = yaml.safe_load((ROOT / "config/laws.yaml").read_text(encoding="utf-8"))
        names += [r["name"] for r in conn.execute("SELECT name FROM regulation.law_seed ORDER BY name").fetchall()
                  if r["name"] not in names]
```

- [ ] **Step 4: 통과 확인 후 커밋** — `uv run pytest tests/test_refs.py -q` → 6 PASS

```bash
git add src/reg/refs.py src/reg/cli.py tests/test_refs.py
git commit -m "feat(refs): rule-based reference extraction and resolution with law seeds"
```

---

### Task 5: 품질 검사와 검수 큐, 목차 기록

**Files:**
- Create: `src/reg/quality.py`, `tests/test_quality.py`
- Modify: `src/reg/structure/parse.py`. 머리부의 목차 줄에서 조 키 목록을 `meta["toc"]`에 기록한다(3개 이상일 때만).

**Interfaces:**
- Produces:
  - `Issue(kind: str, detail: dict)` (dataclass)
  - `check(doc: ParsedDoc, eff: Effective) -> list[Issue]`
    - `CONFLICT`: `eff.status == "CONFLICT"`일 때
    - `EFFECTIVE_DATE`: `eff.status == "UNCERTAIN"`일 때
    - `PARSE` (gap): 본문 조 번호(가지조 제외) 1..max 사이에 빠진 번호가 있을 때. 삭제 조문은 있는 것으로 본다.
    - `PARSE` (toc): `meta["toc"]`와 본문 조 키 집합이 다를 때. 목차가 없으면 검사하지 않는다.
    - `LOW_TEXT`: 조가 0개이거나, 조 본문 평균 길이가 10자 미만일 때
  - `record(conn, work_id: str, version_id: str, issues: list[Issue]) -> str`
    - 검수 작업의 `target`은 버전 id다. 단, `REFERENCE`는 `ref:{reference.id}`다.
    - `ON CONFLICT (kind, target) DO UPDATE SET detail = EXCLUDED.detail`
    - `work_version.validation_status`를 갱신하고 그 값을 돌려준다.
  - `record_reference_tasks(conn, work_id: str) -> int`
    - 미해석 외부 참조(`EXTERNAL_UNRESOLVED`)마다 `REFERENCE` 작업을 하나씩 만든다.

- [ ] **Step 1: 실패하는 테스트**

```python
# tests/test_quality.py
from datetime import date
from pathlib import Path

from reg.extract import extract
from reg.quality import Issue, check, record
from reg.structure.effective import Effective
from reg.structure.model import ParsedDoc, Prov
from reg.structure.parse import parse_blocks

S = Path(__file__).parent / "fixtures" / "samples"
OK = Effective(date(2024, 1, 1), "supplement", "CONFIRMED", None)


def arts(*nums, deleted=()):
    return ParsedDoc("x", None, [], [Prov(f"a{n}", "article", f"제{n}조", "t", "삭제" if n in deleted else "본문입니다 충분히",
                                          deleted=n in deleted) for n in nums])


def test_gap_detected_and_deleted_counts_as_present():
    assert [i.kind for i in check(arts(1, 2, 4), OK)] == ["PARSE"]
    assert check(arts(1, 2, 3, deleted=(2,)), OK) == []


def test_effective_status_issues():
    assert [i.kind for i in check(arts(1), Effective(None, "none", "UNCERTAIN", None))] == ["EFFECTIVE_DATE"]
    assert [i.kind for i in check(arts(1), Effective(date(2024, 1, 1), "supplement", "CONFLICT", None))] == ["CONFLICT"]


def test_kasi_toc_matches_body_and_nst_has_no_toc():
    kasi = parse_blocks(extract((S / "kasi-yeobi-339.pdf").read_bytes(), "application/pdf", "a.pdf"))
    assert len(kasi.meta["toc"]) >= 20 and check(kasi, OK) == []
    nst = parse_blocks(extract((S / "nst-yeobi-18.hwp").read_bytes(), "application/x-hwp", "a.hwp"))
    assert "toc" not in nst.meta and all(i.detail.get("check") != "toc" for i in check(nst, OK))


def test_record_is_idempotent_and_sets_status(conn, tmp_path):
    from tests.test_refs import _load

    _load(conn, tmp_path, "kr/reg/X/a", "INTERNAL_REG", "a", [Prov("a1", "article", "제1조", "t", "본문입니다")])
    vid = conn.execute("SELECT id FROM regulation.work_version").fetchone()["id"]
    issues = [Issue("PARSE", {"check": "gap", "missing": [3]}), Issue("EFFECTIVE_DATE", {})]
    assert record(conn, "kr/reg/X/a", vid, issues) == "REVIEW"
    record(conn, "kr/reg/X/a", vid, issues)
    assert conn.execute("SELECT count(*) AS n FROM regulation.review_task").fetchone()["n"] == 2
    assert record(conn, "kr/reg/X/a", vid, [Issue("EFFECTIVE_DATE", {})]) == "PASSED"
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_quality.py -q` → FAIL

- [ ] **Step 3: 구현**

`src/reg/structure/parse.py`: `parse_blocks`에서 `title, code, hist = _header(blocks[:start])` 다음 줄에 추가한다.

```python
    toc = []
    for b in blocks[:start]:
        if (m := RE_ARTICLE.match(b.text)) and not m[3]:
            k = _article_key(m[1], m[2])
            if k not in toc:
                toc.append(k)
```

그리고 반환하는 `ParsedDoc`의 meta를 `{"stats": st, **({"toc": toc} if len(toc) >= 3 else {})}`로 바꾼다.

```python
# src/reg/quality.py
"""품질 검사와 검수 큐 기록 (spec 6.5)."""
import json
import re
from dataclasses import dataclass, field

from reg.structure.effective import Effective
from reg.structure.model import ParsedDoc

BLOCKING = {"PARSE", "CONFLICT", "LOW_TEXT"}


@dataclass
class Issue:
    kind: str
    detail: dict = field(default_factory=dict)


def check(doc: ParsedDoc, eff: Effective) -> list[Issue]:
    out = []
    if eff.status == "CONFLICT":
        out.append(Issue("CONFLICT", {"basis": eff.basis}))
    elif eff.status == "UNCERTAIN":
        out.append(Issue("EFFECTIVE_DATE", {"basis": eff.basis}))
    arts = [p for p in doc.provisions if p.unit == "article"]
    if not arts or sum(len(p.text) for p in arts) / len(arts) < 10 and not all(p.deleted for p in arts):
        out.append(Issue("LOW_TEXT", {"articles": len(arts)}))
        return out
    nums = {int(m[1]) for p in arts if (m := re.fullmatch(r"a(\d+)(?:~\d+)?", p.path))}
    missing = sorted(set(range(1, max(nums) + 1)) - nums) if nums else []
    if missing:
        out.append(Issue("PARSE", {"check": "gap", "missing": missing[:20]}))
    toc = doc.meta.get("toc")
    if toc:
        body = {p.path for p in arts}
        diff = sorted(set(toc) ^ body)
        if diff:
            out.append(Issue("PARSE", {"check": "toc", "diff": diff[:20]}))
    return out


def record(conn, work_id: str, version_id: str, issues: list[Issue]) -> str:
    kinds = set()
    for i in issues:
        conn.execute("INSERT INTO regulation.review_task (kind, target, work_id, detail) VALUES (%s,%s,%s,%s)"
                     " ON CONFLICT (kind, target) DO UPDATE SET detail = EXCLUDED.detail",
                     (i.kind, version_id, work_id, json.dumps(i.detail, ensure_ascii=False)))
        kinds.add(i.kind)
    conn.execute("UPDATE regulation.review_task SET status = 'RESOLVED', resolved_at = now()"
                 " WHERE target = %s AND status = 'OPEN' AND NOT (kind = ANY(%s))", (version_id, list(kinds)))
    status = "REVIEW" if kinds & BLOCKING else "PASSED"
    conn.execute("UPDATE regulation.work_version SET validation_status = %s WHERE id = %s", (status, version_id))
    return status


def record_reference_tasks(conn, work_id: str) -> int:
    rows = conn.execute("SELECT id, target_name, evidence_text FROM regulation.reference WHERE work_id = %s"
                        " AND target_kind = 'EXTERNAL_UNRESOLVED'", (work_id,)).fetchall()
    for r in rows:
        conn.execute("INSERT INTO regulation.review_task (kind, target, work_id, detail) VALUES ('REFERENCE', %s, %s, %s)"
                     " ON CONFLICT (kind, target) DO NOTHING",
                     (f"ref:{r['id']}", work_id, json.dumps({"name": r["target_name"], "evidence": r["evidence_text"]},
                                                           ensure_ascii=False)))
    return len(rows)
```

- [ ] **Step 4: 통과 확인 후 커밋** — `uv run pytest -q` → 전체 PASS

```bash
git add src/reg/quality.py src/reg/structure/parse.py tests/test_quality.py
git commit -m "feat(quality): checks, review queue and table-of-contents capture"
```

---

### Task 6: 처리기 연결과 전체 재처리

**Files:**
- Modify: `src/reg/process.py`, `src/reg/cli.py`
- Create: `tests/test_process_m2b.py`

**Interfaces:**
- Consumes: Task 2~5
- Produces:
  - `process_once(conn, blob, limit=100, today=None, converter: Converter | None = None) -> dict`
    - `converter`가 None이면 변환 단계를 건너뛴다.
    - 반환값은 M2a와 같은 키를 쓴다.
  - `handle_source_fetched` 순서
    1. 보기용 PDF와 원문 위치
       - HWP·HWPX이고 변환기가 있으면: 보기용 PDF를 만들어 `view/{sha}.pdf`에 저장하고 `view_status='ready'`로 둔다. 이어서 `locate`로 원문 위치를 붙인다.
       - 변환에 실패하면 `view_status='failed'`로 남기고 계속 진행한다.
       - PDF면 `view_blob_key=blob_key`, `view_status='not_needed'`로 둔다.
    2. 적재: `add_version`, `rebuild_work`
    3. 참조: `resolve_and_store`, `record_reference_tasks`
    4. 품질: `record(check(doc, eff))`
  - `handle_law_fetched`: 적재 뒤에 `resolve_and_store`와 `record(check(...))`를 똑같이 수행한다. 법령에는 보기용 PDF가 없다(law.go.kr 원문 링크로 대신한다).
  - `rebuild_all(conn) -> int`
    - 비우는 대상: `reference`, `review_task`, `provision_change`, `version_provision`, `provision_version`, `provision`, `amendment_history`, `work_version`, `work`
    - 수집 이벤트(TOPICS)를 다시 처리할 수 있게 `processed_at=NULL`, `attempts=0`, `last_error=NULL`로 되돌린다.
    - 되돌린 이벤트 수를 돌려준다.
  - CLI `reg process --rebuild`: `rebuild_all`을 실행한 뒤 `--all`처럼 끝까지 처리한다.
  - CLI의 변환기는 `DockerConverter()`이고, `--no-convert` 옵션이면 None이다.

- [ ] **Step 1: 실패하는 테스트**

```python
# tests/test_process_m2b.py
from datetime import date
from pathlib import Path

from reg.process import process_once, rebuild_all
from reg.storage.blob import LocalBlobStore
from tests.test_process import seed_alio

S = Path(__file__).parent / "fixtures" / "samples"
TODAY = date(2026, 10, 2)


class FakeConverter:
    def __init__(self, pdf: bytes | None):
        self.pdf, self.calls = pdf, 0

    def to_pdf(self, data, ext):
        self.calls += 1
        if self.pdf is None:
            from reg.views.converter import ConversionError
            raise ConversionError("no docker")
        return self.pdf


def test_hwp_gets_view_pdf_anchors_refs_and_validation(conn, tmp_path):
    blob = LocalBlobStore(tmp_path)
    seed_alio(conn, blob, (S / "nst-yeobi-18.hwp").read_bytes(), file_name="여비규정(제18차 개정).hwp")
    conn.execute("UPDATE regulation.source_document SET mime='application/x-hwp'")
    conn.commit()
    conv = FakeConverter((S / "nst-yeobi-18.view.pdf").read_bytes())
    assert process_once(conn, blob, today=TODAY, converter=conv)["ok"] == 1
    sd = conn.execute("SELECT view_blob_key, view_status FROM regulation.source_document").fetchone()
    assert sd["view_status"] == "ready" and blob.exists(sd["view_blob_key"])
    a = conn.execute("SELECT source_anchor FROM regulation.provision_version WHERE path='a9-2'").fetchone()
    assert a["source_anchor"]["page"] == 5
    n = conn.execute("SELECT count(*) AS n FROM regulation.reference").fetchone()["n"]
    assert n > 10
    v = conn.execute("SELECT validation_status FROM regulation.work_version").fetchone()
    assert v["validation_status"] in ("PASSED", "REVIEW")


def test_converter_failure_does_not_fail_event(conn, tmp_path):
    blob = LocalBlobStore(tmp_path)
    seed_alio(conn, blob, (S / "nst-yeobi-18.hwp").read_bytes(), file_name="여비규정.hwp")
    conn.execute("UPDATE regulation.source_document SET mime='application/x-hwp'")
    conn.commit()
    assert process_once(conn, blob, today=TODAY, converter=FakeConverter(None))["ok"] == 1
    assert conn.execute("SELECT view_status FROM regulation.source_document").fetchone()["view_status"] == "failed"


def test_rebuild_all_reprocesses_from_outbox(conn, tmp_path):
    blob = LocalBlobStore(tmp_path)
    seed_alio(conn, blob, (S / "kasi-yeobi-339.pdf").read_bytes())
    process_once(conn, blob, today=TODAY)
    n_pv = conn.execute("SELECT count(*) AS n FROM regulation.provision_version").fetchone()["n"]
    assert rebuild_all(conn) == 1
    assert conn.execute("SELECT count(*) AS n FROM regulation.work").fetchone()["n"] == 0
    process_once(conn, blob, today=TODAY)
    assert conn.execute("SELECT count(*) AS n FROM regulation.provision_version").fetchone()["n"] == n_pv
    assert conn.execute("SELECT view_status FROM regulation.source_document").fetchone()["view_status"] == "not_needed"
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_process_m2b.py -q` → FAIL (`ImportError: rebuild_all`)

- [ ] **Step 3: 구현**

`src/reg/process.py`에서 바꾸는 부분은 다음과 같다.

1. import에 아래를 추가한다.
   - `from reg.extract.pdf import extract_pdf`
   - `from reg.quality import check, record, record_reference_tasks`
   - `from reg.refs import resolve_and_store`
   - `from reg.views.anchor import locate`
   - `from reg.views.converter import ConversionError, Converter`
2. 모듈 상단에 다음을 둔다.

```python
HWP_MIMES = {"application/x-hwp": "hwp", "application/hwp+zip": "hwpx"}
STRUCTURE_TABLES = ["reference", "review_task", "provision_change", "version_provision", "provision_version",
                    "provision", "amendment_history", "work_version", "work"]


def _view(conn, blob, sd, doc, converter) -> None:
    if sd["mime"] == "application/pdf":
        conn.execute("UPDATE regulation.source_document SET view_blob_key = blob_key, view_status = 'not_needed'"
                     " WHERE id = %s", (sd["id"],))
        return
    if converter is None or sd["mime"] not in HWP_MIMES:
        return
    try:
        pdf = converter.to_pdf(blob.get(sd["blob_key"]), HWP_MIMES[sd["mime"]])
    except ConversionError:
        conn.execute("UPDATE regulation.source_document SET view_status = 'failed' WHERE id = %s", (sd["id"],))
        return
    key = f"view/{sd['sha256']}.pdf"
    if not blob.exists(key):
        blob.put(key, pdf, "application/pdf")
    conn.execute("UPDATE regulation.source_document SET view_blob_key = %s, view_status = 'ready' WHERE id = %s",
                 (key, sd["id"]))
    locate(doc, extract_pdf(pdf))


def _after_load(conn, wid: str, vid: str, doc, eff) -> None:
    resolve_and_store(conn, wid)
    record_reference_tasks(conn, wid)
    record(conn, wid, vid, check(doc, eff))


def rebuild_all(conn) -> int:
    conn.execute("TRUNCATE " + ", ".join(f"regulation.{t}" for t in STRUCTURE_TABLES) + " CASCADE")
    n = conn.execute("UPDATE regulation.outbox SET processed_at = NULL, attempts = 0, last_error = NULL"
                     " WHERE topic = ANY(%s)", (list(TOPICS),)).rowcount
    conn.commit()
    return n
```

3. `handle_source_fetched(conn, blob, payload, today, converter=None)`
   - `eff = resolve(...)` 다음에 `_view(conn, blob, sd, doc, converter)`를 호출한다.
   - `add_version(...)`의 반환값을 `vid`로 받는다.
   - `rebuild_work` 다음에 `_after_load(conn, wid, vid, doc, eff)`를 호출한다.
4. `handle_law_fetched(conn, blob, payload, today, converter=None)`
   - `eff = resolve(doc)`, `vid = add_version(conn, wid, sd["id"], doc, eff)`, `rebuild_work(...)`, `_after_load(conn, wid, vid, doc, eff)` 순서로 호출한다.
5. `process_once`
   - 시그니처에 `converter: Converter | None = None`을 추가한다.
   - 핸들러 호출을 `HANDLERS[ev["topic"]](conn, blob, ev["payload"], today, converter)`로 바꾼다.

`src/reg/cli.py`의 `process_cmd`에서 바꾸는 부분은 다음과 같다.
- 옵션 `rebuild: bool = typer.Option(False, "--rebuild")`, `no_convert: bool = typer.Option(False, "--no-convert")`를 추가한다.
- body 첫 줄에 `if rebuild: rebuild_all(conn)`을 넣고, 이 경우 `all_ = True`로 다룬다.
- `process_once(conn, _blob(), limit=limit, converter=None if no_convert else DockerConverter())`로 호출한다.
- import에 `from reg.process import process_once, rebuild_all`와 `from reg.views.converter import DockerConverter`를 추가한다.

- [ ] **Step 4: 통과 확인 후 커밋** — `uv run pytest -q` → 전체 PASS

```bash
git add src/reg/process.py src/reg/cli.py tests/test_process_m2b.py
git commit -m "feat(process): view PDFs, anchors, references and quality in the pipeline; rebuild command"
```

---

### Task 7: 실데이터 전체 재처리와 보고

**Files:**
- Create: `docs/reports/2026-10-02-m2-pilot-load.md`. M2a Task 8 보고서와 합쳐서 하나로 쓴다.

- [ ] **Step 1: 마이그레이션과 재처리**

```bash
set -a; . ./.env; set +a
uv run reg db upgrade
uv run reg collect law                     # law_seed 반영 전 기본 법령
uv run reg process --rebuild               # HWP 변환 포함 (파일당 약 3초)
uv run reg collect law && uv run reg process --all   # 참조로 발견된 법령 수집과 처리
```

Expected:
- `failed`가 0이다. 실패한 이벤트가 있으면 원인별 건수를 보고서에 적는다.
- HWP 문서의 `view_status='ready'` 비율이 95% 이상이다.

- [ ] **Step 2: 확인 쿼리를 실행하고 그 결과를 보고서에 적는다**

```sql
select split_part(w.id,'/',3) inst, count(distinct w.id) works, count(*) versions,
  count(*) filter (where version_state='CURRENT') current,
  count(*) filter (where effective_status='CONFIRMED') confirmed,
  count(*) filter (where validation_status='REVIEW') review
from regulation.work_version v join regulation.work w on w.id=v.work_id group by 1 order by 1;
select rel_type, target_kind, resolution, count(*) from regulation.reference group by 1,2,3 order by 4 desc;
select kind, count(*) from regulation.review_task where status='OPEN' group by 1;
select view_status, count(*) from regulation.source_document group by 1;
```

천문연 여비규정 현행 버전의 `a27.p3` 참조가 `EXCEPTION → a27.p1`인지 확인한다.

- [ ] **Step 3: 커밋**

```bash
git add docs/reports/2026-10-02-m2-pilot-load.md README.md
git commit -m "docs: M2 pilot load report"
```

---

## Self-Review 결과

**스펙 대응**

| 스펙 | 반영 위치 |
|---|---|
| 6.2 보기용 PDF | Task 2, 6 |
| 10 원문 대조용 위치 | Task 3 |
| 6.4 참조와 미해석 처리 | Task 4 |
| 6.1 참조로 발견한 법령 자동 수집 | Task 4 `law_seed` + CLI |
| 6.5 품질 검사·검수 큐 | Task 5 |
| 6.6·7 재처리 | Task 6 |

**다음 단계로 넘기는 항목**
- `IMPLEMENTS` 관계 → M5 그래프
- 별표 표 구조화(`attachment.table_json`)는 M3 뷰어에서 보기용 PDF로 대신한다. 이 판단은 M3 계획에 남긴다.

**타입 일치**
- `Converter.to_pdf(data, ext)`의 `ext`는 `hwp` 또는 `hwpx`다.
- `HANDLERS` 시그니처 `(conn, blob, payload, today, converter)`가 Task 6에서 하나로 맞춰진다.
- `record()`의 반환값은 `validation_status`다.
