# M3 규정 API·뷰어 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** M2가 적재한 규정·법령을 LLM 없이 열람하는 기능을 만든다.

- **API**: 읽기 전용 HTTP API(FastAPI, `:21061`)
- **웹 화면**: law.go.kr형 웹 화면(Next.js 16, `:21060`)
  - 기관별 규정 목록
  - 조문 뷰어: 목차·본문·관계 패널·연혁·기준일
  - 원문 대조: PDF 위 강조 표시
  - 신구 비교
  - 키워드 검색
  - 검수 큐 열람

**Architecture:**
- **API** (`reg.api`)
  - psycopg 연결 풀로 `regulation` 스키마를 읽고, 원본·보기용 PDF는 BlobStore에서 스트리밍한다.
  - work id에 `/`가 들어가므로 work id는 경로가 아니라 쿼리(`?id=`)로 받는다.
- **웹** (`apps/web`)
  - 다른 세션이 만든 Next 16 골격을 쓴다. 의존성은 next 16.3.8, react 19.2, react-pdf 11, tailwind 4다.
  - 서버 컴포넌트가 API를 직접 부르고(`cache: 'no-store'`), 브라우저 쪽 요청은 `rewrites`로 `/api/*`를 API에 넘긴다.
  - 디자인은 `docs/ui/*.dc.html` 시안을 따른다.
    - 글꼴: IBM Plex Sans KR(UI), Noto Serif KR(조문)
    - 색: 바탕 `#F4F5F7`, 글자 `#16191D`, 강조 `#1E4FAF`
- **인증**: 이번 범위는 읽기 전용이다. API와 웹은 내부망에만 공개한다. 검수 결정 같은 쓰기와 Keycloak 연동은 M5에서 한다.

**Tech Stack:**
- Python: FastAPI, uvicorn, psycopg-pool
- Web: Next.js 16.3.8 (App Router, Turbopack), React 19.2, Tailwind 4, react-pdf 11

**Spec:** `docs/superpowers/specs/2026-10-01-regulation-platform-design.md` (10 웹 UI, 4.1 포트, NFR-02)

## Global Constraints

- **포트**
  - API: `0.0.0.0:21061`
  - 웹: `0.0.0.0:21060`
  - 둘 다 내부망 192.168.0.x에서 접속한다.
- **API 경로 접두사**: `/api/v1`. 날짜는 ISO `YYYY-MM-DD`다.
- **웹**: Next 16 규칙을 따른다(`apps/web/AGENTS.md`).
  - `params`와 `searchParams`는 Promise로 받는다(`await`).
  - 서버에서의 fetch는 `{ cache: "no-store" }`로 한다.
  - 클라이언트 컴포넌트에만 `"use client"`를 붙인다.
- **화면 문구**: 한국어로 쓴다. 날짜는 `2024. 1. 17.` 형식으로 보여준다.
- **없는 기능**(질의응답, 개정 알림)은 메뉴에 넣지 않는다. 가짜 화면을 만들지 않는다.

## Review Focus

1. **한글과 슬래시가 든 work id**(`kr/reg/KASI/여비규정`)가 URL 왕복 뒤에도 같은 work를 가리켜야 한다. Task 1과 Task 4에서 테스트한다.
2. **현행 버전이 없는 work**(미래 시행본만 있거나 날짜가 없는 경우). 목록과 뷰어가 죽지 않고 가장 최근 버전을 보여주며 상태를 표시해야 한다. Task 1에서 테스트한다.
3. **기준일이 첫 시행일보다 이른 경우.** 404와 함께 "그 날짜에 시행 중인 버전이 없습니다"라고 안내해야 한다. Task 1에서 테스트한다.
4. **보기용 PDF가 없는 버전**(변환 실패, 법령 XML). 원문 대조 화면이 오류 없이 원본 다운로드나 law.go.kr 링크로 안내해야 한다. Task 1과 Task 5에서 테스트한다.
5. **검색어에 `%`, `_`, 따옴표가 들어간 경우.** SQL LIKE 와일드카드로 해석되거나 오류가 나면 안 된다. Task 2에서 테스트한다.

---

## File Structure

```
src/reg/api/__init__.py
src/reg/api/app.py          # create_app(dsn, blob) — 라우터 등록, 연결 풀
src/reg/api/queries.py      # SQL과 결과 가공 (work 목록, 버전 선택, 조문, 참조, diff, 검색, 검수)
src/reg/cli.py              # (수정) reg api
tests/test_api.py
apps/web/
├── next.config.ts          # rewrites /api → :21061
├── package.json            # scripts: dev/start -p 21060 -H 0.0.0.0, postinstall pdf worker 복사
├── src/lib/api.ts          # 서버 fetch, 타입, URL 인코딩
├── src/lib/format.ts       # 날짜·상태 라벨
├── src/app/layout.tsx      # 글꼴, 머리 내비게이션
├── src/app/globals.css     # 색·칩·버튼 토큰
├── src/app/page.tsx        # → /regulations
├── src/app/regulations/page.tsx
├── src/app/regulations/[...id]/page.tsx          # 조문 뷰어
├── src/app/regulations/[...id]/source/page.tsx   # 원문 대조
├── src/app/compare/page.tsx
├── src/app/search/page.tsx
├── src/app/review/page.tsx
├── src/components/ProvisionText.tsx   # 참조 링크가 들어간 조문 본문
├── src/components/Relations.tsx       # (client) 관계 패널
└── src/components/PdfPane.tsx         # (client) react-pdf + 강조 박스
scripts/run-dev.sh                     # API·웹 백그라운드 실행
```

---

### Task 1: API — 기관·work·버전·조문·파일

**Files:**
- Create: `src/reg/api/__init__.py`, `src/reg/api/app.py`, `src/reg/api/queries.py`, `tests/test_api.py`
- Modify: `pyproject.toml`에 `fastapi>=0.115`, `uvicorn>=0.30`, `psycopg-pool>=3.2`를 추가한다.

**Interfaces:**
- Produces: `create_app(dsn: str, blob: BlobStore) -> FastAPI`
- 엔드포인트 (모두 GET)

  | 경로 | 응답 |
  |---|---|
  | `/api/v1/institutions` | `[{code, name, kind, works}]` |
  | `/api/v1/works?institution=&kind=law\|reg&q=` | `[{id, title, kind, institution, version: {id, effective_from, version_state, effective_status, validation_status, amendment_no} \| null}]` |
  | `/api/v1/work/versions?id=` | `[{id, effective_from, effective_to, version_state, effective_status, effective_basis, amendment_kind, amendment_no, promulgated_on, validation_status}]` (시행일 내림차순) |
  | `/api/v1/work/view?id=&as_of=` | 아래 참고 |
  | `/api/v1/file?version=&kind=view\|original` | 파일 본문 |

- `/api/v1/work/view` 응답: `{work, version, provisions, refs, history, tasks}`
  - `work`: `{id, title, kind, institution}`
  - `version`: 버전 메타데이터 + `{source: {source, url, mime, view_status, file_name, has_view}}`
  - `provisions`: `[{id, provision_id, path, unit, label, heading, text, parent, annotations, deleted, anchor, effective_override}]` (문서 순서)
  - `refs`: `{pv_id: [{start, end, rel_type, target_kind, target_work_id, target_path, target_name, resolution}]}`
  - `history`: `[{kind, date, number}]`
  - `tasks`: `[{kind, detail}]` (열린 검수 작업)
  - 버전 선택 규칙
    - `as_of`가 있으면 그 날짜에 시행 중인 버전을 고른다. 없으면 404 `{"detail": "그 날짜에 시행 중인 버전이 없습니다"}`
    - `as_of`가 없으면 `CURRENT`를 고른다. 없으면 시행일이 가장 늦은 버전, 그것도 없으면 가장 최근에 적재된 버전을 고른다.
- `/api/v1/file`
  - `kind=view`: 보기용 PDF가 없으면 404
  - `kind=original`: 원본 mime과 `Content-Disposition: attachment; filename*=UTF-8''…`을 붙여 보낸다.

- [ ] **Step 1: 실패하는 테스트**

```python
# tests/test_api.py
from datetime import date
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from reg.api.app import create_app
from reg.process import process_once
from reg.storage.blob import LocalBlobStore
from tests.test_process import seed_alio

S = Path(__file__).parent / "fixtures" / "samples"
WID = "kr/reg/KASI/여비규정"


@pytest.fixture
def api(conn, migrated, tmp_path):
    blob = LocalBlobStore(tmp_path)
    seed_alio(conn, blob, (S / "kasi-yeobi-339.pdf").read_bytes())
    process_once(conn, blob, today=date(2026, 10, 2))
    with TestClient(create_app(migrated[0], blob)) as c:
        yield c


def test_institutions_and_works(api):
    inst = api.get("/api/v1/institutions").json()
    assert {"code": "KASI", "name": "한국천문연구원", "kind": "GRI", "works": 1} in inst
    works = api.get("/api/v1/works", params={"institution": "KASI"}).json()
    assert works[0]["id"] == WID and works[0]["version"]["effective_from"] == "2024-01-17"
    assert api.get("/api/v1/works", params={"q": "여비"}).json()[0]["id"] == WID


def test_view_current_with_refs_and_unicode_id(api):
    r = api.get(f"/api/v1/work/view?id={quote(WID, safe='')}")
    assert r.status_code == 200
    v = r.json()
    assert v["work"]["title"] == "여비규정" and v["version"]["version_state"] == "CURRENT"
    p = {x["path"]: x for x in v["provisions"]}
    assert "7일 이내에" in p["a27.p1"]["text"] and p["a27"]["anchor"]["page"] == 12
    refs = v["refs"][str(p["a27.p3"]["id"])]
    assert any(x["rel_type"] == "EXCEPTION" and x["target_path"] == "a27.p1" for x in refs)
    assert v["history"][-1]["number"] == "339" and v["version"]["source"]["has_view"] is True


def test_as_of_before_first_version_is_404(api):
    r = api.get("/api/v1/work/view", params={"id": WID, "as_of": "1990-01-01"})
    assert r.status_code == 404 and "시행 중인 버전이 없습니다" in r.json()["detail"]


def test_versions_and_files(api):
    vs = api.get("/api/v1/work/versions", params={"id": WID}).json()
    assert vs[0]["effective_from"] == "2024-01-17"
    f = api.get("/api/v1/file", params={"version": vs[0]["id"], "kind": "view"})
    assert f.status_code == 200 and f.content.startswith(b"%PDF") and f.headers["content-type"] == "application/pdf"
    o = api.get("/api/v1/file", params={"version": vs[0]["id"], "kind": "original"})
    assert "filename*=UTF-8''" in o.headers["content-disposition"]


def test_unknown_work_404(api):
    assert api.get("/api/v1/work/view", params={"id": "kr/reg/NONE/x"}).status_code == 404
```

- [ ] **Step 2: 실패 확인** — `uv add fastapi uvicorn psycopg-pool && uv run pytest tests/test_api.py -q` → FAIL (`ModuleNotFoundError: reg.api`)

- [ ] **Step 3: 구현**

```python
# src/reg/api/__init__.py
```

```python
# src/reg/api/queries.py
"""API용 조회. 모든 함수는 dict_row 연결을 받는다."""
from datetime import date

VERSION_COLS = ("v.id, v.work_id, v.title, v.effective_from, v.effective_to, v.version_state, v.effective_status,"
                " v.effective_basis, v.validation_status, v.amendment_kind, v.amendment_no, v.promulgated_on,"
                " v.posted_on, v.class_code, v.source_document_id")


def institutions(conn) -> list[dict]:
    return conn.execute(
        "SELECT i.code, i.name, i.kind, count(w.id)::int AS works FROM regulation.institution i"
        " LEFT JOIN regulation.work w ON w.institution_id = i.id GROUP BY i.id ORDER BY i.id").fetchall()


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def works(conn, institution: str | None, kind: str | None, q: str | None) -> list[dict]:
    rows = conn.execute(
        "SELECT w.id, w.title, w.kind, i.code AS institution,"
        " (SELECT row_to_json(x) FROM (SELECT v.id, v.effective_from, v.version_state, v.effective_status,"
        "   v.validation_status, v.amendment_no FROM regulation.work_version v WHERE v.work_id = w.id"
        "   ORDER BY (v.version_state = 'CURRENT') DESC, v.effective_from DESC NULLS LAST, v.created_at DESC"
        "   LIMIT 1) x) AS version"
        " FROM regulation.work w LEFT JOIN regulation.institution i ON i.id = w.institution_id"
        " WHERE (%(inst)s::text IS NULL OR i.code = %(inst)s)"
        "   AND (%(kind)s::text IS NULL OR (%(kind)s = 'law') = (w.id LIKE 'kr/law/%%'))"
        "   AND (%(q)s::text IS NULL OR w.title ILIKE %(q)s ESCAPE '\\')"
        " ORDER BY i.code NULLS LAST, w.title LIMIT 1000",
        {"inst": institution, "kind": kind, "q": _like(q) if q else None}).fetchall()
    return rows


def work(conn, work_id: str) -> dict | None:
    return conn.execute("SELECT w.id, w.title, w.kind, i.code AS institution FROM regulation.work w"
                        " LEFT JOIN regulation.institution i ON i.id = w.institution_id WHERE w.id = %s",
                        (work_id,)).fetchone()


def versions(conn, work_id: str) -> list[dict]:
    return conn.execute(f"SELECT {VERSION_COLS} FROM regulation.work_version v WHERE v.work_id = %s"
                        " ORDER BY v.effective_from DESC NULLS LAST, v.created_at DESC", (work_id,)).fetchall()


def pick_version(conn, work_id: str, as_of: date | None) -> dict | None:
    if as_of:
        return conn.execute(
            f"SELECT {VERSION_COLS} FROM regulation.work_version v WHERE v.work_id = %s AND v.effective_from <= %s"
            " AND (v.effective_to IS NULL OR v.effective_to > %s) ORDER BY v.effective_from DESC LIMIT 1",
            (work_id, as_of, as_of)).fetchone()
    return conn.execute(
        f"SELECT {VERSION_COLS} FROM regulation.work_version v WHERE v.work_id = %s"
        " ORDER BY (v.version_state = 'CURRENT') DESC, v.effective_from DESC NULLS LAST, v.created_at DESC LIMIT 1",
        (work_id,)).fetchone()


def version_by_id(conn, version_id: str) -> dict | None:
    return conn.execute(f"SELECT {VERSION_COLS} FROM regulation.work_version v WHERE v.id = %s",
                        (version_id,)).fetchone()


def source(conn, source_document_id: int) -> dict:
    sd = conn.execute("SELECT id, source, url, mime, blob_key, view_blob_key, view_status, source_meta"
                      " FROM regulation.source_document WHERE id = %s", (source_document_id,)).fetchone()
    return sd


def provisions(conn, version_id: str) -> list[dict]:
    return conn.execute(
        "SELECT pv.id, pv.provision_id, pv.path, pv.unit, pv.number_label AS label, pv.heading, pv.text,"
        " pv.parent_path AS parent, pv.annotations, pv.deleted, pv.source_anchor AS anchor,"
        " pv.effective_from_override AS effective_override"
        " FROM regulation.version_provision vp JOIN regulation.provision_version pv ON pv.id = vp.provision_version_id"
        " WHERE vp.work_version_id = %s ORDER BY vp.ord", (version_id,)).fetchall()


def refs_for(conn, pv_ids: list[int]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in conn.execute(
            "SELECT source_pv_id, span_start AS start, span_end AS end, rel_type, target_kind, target_work_id,"
            " target_path, target_name, resolution FROM regulation.reference WHERE source_pv_id = ANY(%s)"
            " ORDER BY source_pv_id, span_start", (pv_ids,)).fetchall():
        out.setdefault(str(r.pop("source_pv_id")), []).append(r)
    return out


def history(conn, version_id: str) -> list[dict]:
    return conn.execute("SELECT kind, date, number FROM regulation.amendment_history WHERE work_version_id = %s"
                        " ORDER BY ord", (version_id,)).fetchall()


def open_tasks(conn, version_id: str) -> list[dict]:
    return conn.execute("SELECT kind, detail FROM regulation.review_task WHERE target = %s AND status = 'OPEN'",
                        (version_id,)).fetchall()
```

```python
# src/reg/api/app.py
"""읽기 전용 규정 API (spec 10, NFR-02: LLM 없이 열람·검색)."""
from datetime import date
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import Response
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from reg.api import queries as Q
from reg.storage.blob import BlobStore


def create_app(dsn: str, blob: BlobStore) -> FastAPI:
    app = FastAPI(title="NST 규정·법령 API", version="0.3")
    app.state.pool = ConnectionPool(dsn, min_size=1, max_size=8, kwargs={"row_factory": dict_row}, open=False)
    app.state.blob = blob

    @app.on_event("startup")
    def _open() -> None:
        app.state.pool.open()

    @app.on_event("shutdown")
    def _close() -> None:
        app.state.pool.close()

    def conn(request: Request):
        with request.app.state.pool.connection() as c:
            yield c

    @app.get("/api/v1/institutions")
    def institutions(c=Depends(conn)):
        return Q.institutions(c)

    @app.get("/api/v1/works")
    def works(institution: str | None = None, kind: str | None = Query(None, pattern="^(law|reg)$"),
              q: str | None = None, c=Depends(conn)):
        return Q.works(c, institution, kind, q)

    def _work_or_404(c, work_id: str) -> dict:
        w = Q.work(c, work_id)
        if not w:
            raise HTTPException(404, "규정을 찾을 수 없습니다")
        return w

    @app.get("/api/v1/work/versions")
    def versions(id: str, c=Depends(conn)):
        _work_or_404(c, id)
        return Q.versions(c, id)

    @app.get("/api/v1/work/view")
    def view(id: str, as_of: date | None = None, c=Depends(conn)):
        w = _work_or_404(c, id)
        v = Q.pick_version(c, id, as_of)
        if not v:
            raise HTTPException(404, "그 날짜에 시행 중인 버전이 없습니다" if as_of else "버전이 없습니다")
        sd = Q.source(c, v.pop("source_document_id"))
        v["source"] = {"source": sd["source"], "url": sd["url"], "mime": sd["mime"], "view_status": sd["view_status"],
                       "file_name": (sd["source_meta"] or {}).get("file_name"), "has_view": bool(sd["view_blob_key"])}
        provs = Q.provisions(c, v["id"])
        return {"work": w, "version": v, "provisions": provs, "refs": Q.refs_for(c, [p["id"] for p in provs]),
                "history": Q.history(c, v["id"]), "tasks": Q.open_tasks(c, v["id"])}

    @app.get("/api/v1/file")
    def file(version: str, kind: str = Query("view", pattern="^(view|original)$"), c=Depends(conn)):
        v = Q.version_by_id(c, version)
        if not v:
            raise HTTPException(404, "버전을 찾을 수 없습니다")
        sd = Q.source(c, v["source_document_id"])
        if kind == "view":
            if not sd["view_blob_key"]:
                raise HTTPException(404, "보기용 PDF가 없습니다")
            return Response(app.state.blob.get(sd["view_blob_key"]), media_type="application/pdf",
                            headers={"Cache-Control": "private, max-age=3600"})
        name = (sd["source_meta"] or {}).get("file_name") or f"{v['title']}.{sd['blob_key'].rsplit('.', 1)[-1]}"
        return Response(app.state.blob.get(sd["blob_key"]), media_type=sd["mime"],
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})

    return app
```

- [ ] **Step 4: 통과 확인 후 커밋**

Run: `uv run pytest tests/test_api.py -q` → 5 PASS

```bash
git add pyproject.toml uv.lock src/reg/api tests/test_api.py
git commit -m "feat(api): institutions, works, versions, provision view and files"
```

---

### Task 2: API — 참조·신구 비교·검색·검수, `reg api` 명령

**Files:**
- Modify: `src/reg/api/queries.py`, `src/reg/api/app.py`, `src/reg/cli.py`, `tests/test_api.py`

**Interfaces:**
- 엔드포인트 (모두 GET)

  | 경로 | 응답 |
  |---|---|
  | `/api/v1/references?pv=` | `{outgoing, incoming}` (아래 참고) |
  | `/api/v1/diff?from=&to=` | 아래 참고 |
  | `/api/v1/search?q=&institution=` | `[{work_id, title, institution, version_id, path, label, heading, snippet}]` |
  | `/api/v1/review-tasks?status=OPEN&kind=` | `[{id, kind, target, work_id, work_title, detail, status, created_at}]` (최신순, 최대 300) |

- `/api/v1/references`
  - `outgoing`: `[{…ref, target_title}]`
  - `incoming`: `[{…ref, source_work_id, source_title, source_path, source_label}]`
  - `incoming`은 다른 work를 포함해, 현행(`CURRENT`) 버전의 조항 중 이 조항이나 이 조항의 조를 가리키는 참조다.
- `/api/v1/diff`
  - 응답: `{from, to, changes: [{kind, provision_id, path, unit, from: {label, heading, text, annotations} | null, to: {...} | null}]}`
  - `kind` ∈ `ADDED|DELETED|MODIFIED|RENUMBERED|ANNOTATION_ONLY`
  - 변경 없는 조항은 넣지 않는다.
  - 두 버전은 같은 work여야 한다. 아니면 400.
- `/api/v1/search`
  - `q`는 2자 이상이어야 한다. 아니면 422.
  - 현행 버전의 조항 본문을 `ILIKE ... ESCAPE`로 찾는다. `%`, `_`는 글자 그대로 찾는다.
  - `snippet`은 일치 위치 앞뒤 40자다.
  - 최대 50건이다.
- CLI: `reg api [--host 0.0.0.0] [--port 21061]`. `uvicorn.run(create_app(settings.database_url, S3BlobStore(...)))`

- [ ] **Step 1: 실패하는 테스트 (`tests/test_api.py`에 추가)**

```python
from reg.collect.archive import store as _store
from reg.collect.sniff import FileKind
from reg.load.loader import add_version, rebuild_work, upsert_work
from reg.structure.effective import Effective
from reg.structure.model import ParsedDoc, Prov


def test_references_incoming_and_outgoing(api):
    v = api.get("/api/v1/work/view", params={"id": WID}).json()
    p = {x["path"]: x for x in v["provisions"]}
    r = api.get("/api/v1/references", params={"pv": p["a27.p1"]["id"]}).json()
    assert any(x["source_path"] == "a27.p3" and x["rel_type"] == "EXCEPTION" for x in r["incoming"])
    out = api.get("/api/v1/references", params={"pv": p["a29"]["id"]}).json()["outgoing"]
    assert {x["target_name"] for x in out} >= {"공무원 여비규정"}


def test_diff_between_versions(conn, migrated, tmp_path):
    blob = LocalBlobStore(tmp_path)
    upsert_work(conn, "kr/reg/T/규정", "INTERNAL_REG", "규정", None, {})
    ids = []
    for i, (d, provs) in enumerate([(date(2020, 1, 1), [Prov("a1", "article", "제1조", "목적", "옛 본문입니다")]),
                                    (date(2024, 1, 1), [Prov("a1", "article", "제1조", "목적", "새 본문입니다"),
                                                        Prov("a2", "article", "제2조", "정의", "추가된 조문")])]):
        sid = _store(conn, blob, source="alio", url="u", content=b"%PDF" + bytes([i]),
                     kind=FileKind("application/pdf", "pdf"), meta={}).id
        ids.append(add_version(conn, "kr/reg/T/규정", sid, ParsedDoc("규정", None, [], provs),
                               Effective(d, "supplement", "CONFIRMED", d)))
    rebuild_work(conn, "kr/reg/T/규정", date(2026, 10, 2))
    conn.commit()
    with TestClient(create_app(migrated[0], blob)) as c:
        d = c.get("/api/v1/diff", params={"from": ids[0], "to": ids[1]}).json()
        assert sorted((x["kind"], x["path"]) for x in d["changes"]) == [("ADDED", "a2"), ("MODIFIED", "a1")]
        assert c.get("/api/v1/diff", params={"from": ids[0], "to": "nope"}).status_code == 404


def test_search_escapes_wildcards(api):
    hits = api.get("/api/v1/search", params={"q": "7일 이내"}).json()
    assert any(h["path"] == "a27.p1" and "7일 이내" in h["snippet"] for h in hits)
    assert api.get("/api/v1/search", params={"q": "%%"}).json() == []
    assert api.get("/api/v1/search", params={"q": "a"}).status_code == 422


def test_review_tasks_list(api):
    rows = api.get("/api/v1/review-tasks", params={"status": "OPEN"}).json()
    assert isinstance(rows, list) and all(r["status"] == "OPEN" for r in rows)
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_api.py -q` → 새 테스트 4개 FAIL (404)

- [ ] **Step 3: 구현**

`queries.py`에 추가한다.

```python
def references(conn, pv_id: int) -> dict:
    pv = conn.execute("SELECT pv.path, p.work_id FROM regulation.provision_version pv JOIN regulation.provision p"
                      " ON p.id = pv.provision_id WHERE pv.id = %s", (pv_id,)).fetchone()
    if not pv:
        return {"outgoing": [], "incoming": []}
    out = conn.execute(
        "SELECT r.span_start AS start, r.span_end AS end, r.evidence_text, r.rel_type, r.target_kind,"
        " r.target_work_id, r.target_path, r.target_name, r.resolution, tw.title AS target_title"
        " FROM regulation.reference r LEFT JOIN regulation.work tw ON tw.id = r.target_work_id"
        " WHERE r.source_pv_id = %s ORDER BY r.span_start", (pv_id,)).fetchall()
    article = pv["path"].split(".")[0]
    inc = conn.execute(
        "SELECT DISTINCT r.evidence_text, r.rel_type, r.target_path, r.resolution, r.work_id AS source_work_id,"
        " sw.title AS source_title, spv.path AS source_path, spv.number_label AS source_label, spv.id AS source_pv_id"
        " FROM regulation.reference r"
        " JOIN regulation.provision_version spv ON spv.id = r.source_pv_id"
        " JOIN regulation.version_provision vp ON vp.provision_version_id = spv.id"
        " JOIN regulation.work_version sv ON sv.id = vp.work_version_id AND sv.version_state = 'CURRENT'"
        " JOIN regulation.work sw ON sw.id = r.work_id"
        " WHERE r.target_work_id = %(w)s AND (r.target_path = %(p)s OR r.target_path = %(a)s"
        "   OR r.target_path LIKE %(p)s || '.%%' OR (r.target_kind = 'WORK' AND %(p)s = %(a)s))"
        " ORDER BY sw.title, spv.path", {"w": pv["work_id"], "p": pv["path"], "a": article}).fetchall()
    return {"outgoing": out, "incoming": inc}


def _pv_map(conn, version_id: str) -> dict[int, dict]:
    return {r["provision_id"]: r for r in conn.execute(
        "SELECT pv.id, pv.provision_id, pv.path, pv.unit, pv.number_label AS label, pv.heading, pv.text,"
        " pv.text_norm_hash, pv.annotations, vp.ord FROM regulation.version_provision vp"
        " JOIN regulation.provision_version pv ON pv.id = vp.provision_version_id WHERE vp.work_version_id = %s",
        (version_id,)).fetchall()}


def diff(conn, from_id: str, to_id: str) -> list[dict]:
    a, b = _pv_map(conn, from_id), _pv_map(conn, to_id)

    def side(x):
        return {k: x[k] for k in ("label", "heading", "text", "annotations")} if x else None

    out = []
    for pid in sorted(a.keys() | b.keys(), key=lambda k: (b[k]["ord"] if k in b else a[k]["ord"] + 0.5)):
        x, y = a.get(pid), b.get(pid)
        if x and y and x["id"] == y["id"]:
            continue
        if x and y:
            same = x["text_norm_hash"] == y["text_norm_hash"] and x["heading"] == y["heading"]
            kind = "RENUMBERED" if x["path"] != y["path"] else ("ANNOTATION_ONLY" if same else "MODIFIED")
        else:
            kind = "ADDED" if y else "DELETED"
        if kind == "ANNOTATION_ONLY" and x["annotations"] == y["annotations"]:
            continue
        ref = y or x
        out.append({"kind": kind, "provision_id": pid, "path": ref["path"], "unit": ref["unit"],
                    "from": side(x), "to": side(y)})
    return out


def search(conn, q: str, institution: str | None) -> list[dict]:
    rows = conn.execute(
        "SELECT w.id AS work_id, w.title, i.code AS institution, v.id AS version_id, pv.path,"
        " pv.number_label AS label, pv.heading, pv.text"
        " FROM regulation.provision_version pv"
        " JOIN regulation.version_provision vp ON vp.provision_version_id = pv.id"
        " JOIN regulation.work_version v ON v.id = vp.work_version_id AND v.version_state = 'CURRENT'"
        " JOIN regulation.work w ON w.id = v.work_id LEFT JOIN regulation.institution i ON i.id = w.institution_id"
        " WHERE pv.text ILIKE %(q)s ESCAPE '\\' AND (%(inst)s::text IS NULL OR i.code = %(inst)s)"
        " ORDER BY w.title, vp.ord LIMIT 50", {"q": _like(q), "inst": institution}).fetchall()
    for r in rows:
        t, k = r.pop("text"), r["text_low"] if False else None
        pos = t.lower().find(q.lower())
        s = max(pos - 40, 0)
        r["snippet"] = ("…" if s else "") + t[s:pos + len(q) + 40] + ("…" if pos + len(q) + 40 < len(t) else "")
    return rows


def review_tasks(conn, status: str, kind: str | None) -> list[dict]:
    return conn.execute(
        "SELECT t.id, t.kind, t.target, t.work_id, w.title AS work_title, t.detail, t.status, t.created_at"
        " FROM regulation.review_task t LEFT JOIN regulation.work w ON w.id = t.work_id"
        " WHERE t.status = %s AND (%s::text IS NULL OR t.kind = %s) ORDER BY t.created_at DESC, t.id DESC LIMIT 300",
        (status, kind, kind)).fetchall()
```

`app.py`의 `return app` 앞에 추가한다.

```python
    @app.get("/api/v1/references")
    def references(pv: int, c=Depends(conn)):
        return Q.references(c, pv)

    @app.get("/api/v1/diff")
    def diff(from_: str = Query(..., alias="from"), to: str = Query(...), c=Depends(conn)):
        a, b = Q.version_by_id(c, from_), Q.version_by_id(c, to)
        if not a or not b:
            raise HTTPException(404, "버전을 찾을 수 없습니다")
        if a["work_id"] != b["work_id"]:
            raise HTTPException(400, "같은 규정의 버전끼리만 비교할 수 있습니다")
        for v in (a, b):
            v.pop("source_document_id")
        return {"from": a, "to": b, "changes": Q.diff(c, from_, to)}

    @app.get("/api/v1/search")
    def search(q: str = Query(..., min_length=2), institution: str | None = None, c=Depends(conn)):
        return Q.search(c, q, institution)

    @app.get("/api/v1/review-tasks")
    def review_tasks(status: str = Query("OPEN", pattern="^(OPEN|RESOLVED|DISMISSED)$"), kind: str | None = None,
                     c=Depends(conn)):
        return Q.review_tasks(c, status, kind)
```

`cli.py`에 추가한다.

```python
@app.command("api")
def api_cmd(host: str = "0.0.0.0", port: int = 21061) -> None:
    import uvicorn

    from reg.api.app import create_app

    uvicorn.run(create_app(get_settings().database_url, _blob()), host=host, port=port, log_level="info")
```

`search`의 `t, k = r.pop("text"), …` 줄은 `t = r.pop("text")`로 쓴다. 위 코드 블록의 중간 변수는 쓰지 않는다.

- [ ] **Step 4: 통과 확인 후 커밋** — `uv run pytest -q` → 전체 PASS

```bash
git add src/reg/api src/reg/cli.py tests/test_api.py
git commit -m "feat(api): references, version diff, keyword search, review tasks; reg api command"
```

---

### Task 3: 웹 골격 — 설정, 디자인 토큰, 레이아웃, API 클라이언트

**Files:**
- Modify: `apps/web/package.json`, `apps/web/next.config.ts`, `apps/web/src/app/layout.tsx`, `apps/web/src/app/globals.css`, `apps/web/src/app/page.tsx`
- Create: `apps/web/src/lib/api.ts`, `apps/web/src/lib/format.ts`

**Interfaces:**
- Produces (TS):
  - `apiGet<T>(path: string, params?: Record<string, string | undefined>): Promise<T>`
    - 서버 전용이다. `REG_API_URL` 환경변수를 쓰고, 기본값은 `http://127.0.0.1:21061`이다. `cache: "no-store"`로 요청한다.
    - 404면 `null`을 돌려준다. 다른 비정상 응답이면 예외를 던진다.
  - 타입: `Work`, `VersionMeta`, `Provision`, `Ref`, `ViewData`, `VersionRow`, `DiffData`, `SearchHit`, `ReviewTask`
  - `workHref(id: string, extra?: string): string`: 세그먼트마다 `encodeURIComponent`를 적용해 `/regulations/kr/reg/KASI/%EC…` 형태로 만든다.
  - `fmtDate(iso: string | null): string`: `"2024. 1. 17."` 형식, 값이 없으면 `"-"`
  - `STATE_LABEL`, `STATUS_LABEL`, `REL_LABEL`, `CHANGE_LABEL`: 한국어 라벨 사전

- [ ] **Step 1: 설정 파일**

```ts
// apps/web/next.config.ts
import type { NextConfig } from "next";

const API = process.env.REG_API_URL ?? "http://127.0.0.1:21061";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API}/api/:path*` }];
  },
};

export default nextConfig;
```

`apps/web/package.json`의 `scripts`는 다음으로 바꾼다.

```json
"dev": "next dev -p 21060 -H 0.0.0.0",
"build": "next build",
"start": "next start -p 21060 -H 0.0.0.0",
"postinstall": "node -e \"require('fs').copyFileSync(require.resolve('pdfjs-dist/build/pdf.worker.min.mjs',{paths:[require.resolve('react-pdf')]}),'public/pdf.worker.min.mjs')\""
```

- [ ] **Step 2: API 클라이언트와 형식 함수**

```ts
// apps/web/src/lib/api.ts
const BASE = process.env.REG_API_URL ?? "http://127.0.0.1:21061";

export type VersionSummary = {
  id: string; effective_from: string | null; version_state: string; effective_status: string;
  validation_status: string; amendment_no: string | null;
};
export type Work = { id: string; title: string; kind: string; institution: string | null; version?: VersionSummary | null };
export type Institution = { code: string; name: string; kind: string; works: number };
export type VersionRow = VersionSummary & {
  effective_to: string | null; effective_basis: string; amendment_kind: string | null; promulgated_on: string | null;
};
export type VersionMeta = VersionRow & {
  work_id: string; title: string; posted_on: string | null; class_code: string | null;
  source: { source: string; url: string; mime: string; view_status: string; file_name: string | null; has_view: boolean };
};
export type Anchor = { page: number; bbox: [number, number, number, number] | null } | null;
export type Provision = {
  id: number; provision_id: number; path: string; unit: string; label: string; heading: string | null; text: string;
  parent: string | null; annotations: string[]; deleted: boolean; anchor: Anchor; effective_override: string | null;
};
export type Ref = {
  start: number; end: number; rel_type: string; target_kind: string; target_work_id: string | null;
  target_path: string | null; target_name: string | null; resolution: string;
};
export type ViewData = {
  work: Work; version: VersionMeta; provisions: Provision[]; refs: Record<string, Ref[]>;
  history: { kind: string; date: string; number: string | null }[]; tasks: { kind: string; detail: Record<string, unknown> }[];
};
export type Change = {
  kind: string; provision_id: number; path: string; unit: string;
  from: { label: string; heading: string | null; text: string; annotations: string[] } | null;
  to: { label: string; heading: string | null; text: string; annotations: string[] } | null;
};
export type DiffData = { from: VersionRow; to: VersionRow; changes: Change[] };
export type SearchHit = {
  work_id: string; title: string; institution: string | null; version_id: string; path: string; label: string;
  heading: string | null; snippet: string;
};
export type ReviewTask = {
  id: number; kind: string; target: string; work_id: string | null; work_title: string | null;
  detail: Record<string, unknown>; status: string; created_at: string;
};

export async function apiGet<T>(path: string, params: Record<string, string | undefined> = {}): Promise<T | null> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) qs.set(k, v);
  const res = await fetch(`${BASE}${path}${qs.size ? `?${qs}` : ""}`, { cache: "no-store" });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  return (await res.json()) as T;
}

export function workHref(id: string, extra = ""): string {
  return "/regulations/" + id.split("/").map(encodeURIComponent).join("/") + extra;
}

export function decodeSegments(segments: string[]): string {
  return segments.map((s) => { try { return decodeURIComponent(s); } catch { return s; } }).join("/");
}
```

```ts
// apps/web/src/lib/format.ts
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "-";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return `${y}. ${m}. ${d}.`;
}

export const STATE_LABEL: Record<string, string> = {
  CURRENT: "현행", HISTORICAL: "연혁", FUTURE: "시행 예정", UNDATED: "시행일 미상",
};
export const STATUS_LABEL: Record<string, string> = {
  CONFIRMED: "시행일 확인", UNCERTAIN: "시행일 추정", CONFLICT: "시행일 충돌",
};
export const BASIS_LABEL: Record<string, string> = {
  api: "법령 API", supplement: "부칙", history: "개정 이력", alio: "ALIO 개정일", filename: "파일명", none: "근거 없음",
};
export const REL_LABEL: Record<string, string> = {
  BASIS: "근거", DELEGATION: "위임", IMPLEMENTS: "시행", MUTATIS: "준용", EXCEPTION: "예외", CITATION: "참조",
};
export const CHANGE_LABEL: Record<string, string> = {
  ADDED: "신설", DELETED: "삭제", MODIFIED: "개정", RENUMBERED: "조 이동", ANNOTATION_ONLY: "주석만 변경",
};
export const TASK_LABEL: Record<string, string> = {
  PARSE: "구조 파싱", EFFECTIVE_DATE: "시행일", REFERENCE: "참조 해석", CONFLICT: "출처 충돌", LOW_TEXT: "텍스트 부족",
};
```

- [ ] **Step 3: 전역 스타일과 레이아웃**

```css
/* apps/web/src/app/globals.css */
@import "tailwindcss";

:root {
  --ground: #f4f5f7; --surface: #ffffff; --ink: #16191d; --ink-2: #3a414a; --muted: #5a626c;
  --line: #dde1e6; --line-strong: #cdd3db; --accent: #1e4faf; --accent-soft: #e8eefa; --accent-line: #c9d6f0;
  --amber: #9a4a00; --amber-soft: #fbf0e4; --green: #1d5b33; --green-soft: #e3f1e7; --red: #9a3412; --red-soft: #fbe9df;
  --mark: #fff1a8;
}
@theme inline {
  --color-ground: var(--ground); --color-surface: var(--surface); --color-ink: var(--ink); --color-ink-2: var(--ink-2);
  --color-muted: var(--muted); --color-line: var(--line); --color-accent: var(--accent); --color-accent-soft: var(--accent-soft);
  --font-sans: var(--font-ui), system-ui, sans-serif; --font-serif: var(--font-law), serif;
}
body { background: var(--ground); color: var(--ink); }
a { color: var(--accent); }
a:hover { text-decoration: underline; }
.chip { display: inline-flex; align-items: center; height: 24px; padding: 0 9px; border-radius: 999px; font-size: 12px; font-weight: 500; background: #eef1f5; color: var(--ink-2); }
.chip-green { background: var(--green-soft); color: var(--green); }
.chip-blue { background: var(--accent-soft); color: var(--accent); }
.chip-amber { background: var(--amber-soft); color: var(--amber); }
.chip-red { background: var(--red-soft); color: var(--red); }
.btn { display: inline-flex; align-items: center; gap: 6px; height: 36px; padding: 0 14px; border-radius: 8px; border: 1px solid var(--line-strong); background: var(--surface); color: var(--ink); font-size: 13px; transition: transform 160ms ease-out; }
.btn:active { transform: scale(0.97); }
.btn:hover { text-decoration: none; }
.btn-dark { background: var(--ink); color: #fff; border-color: var(--ink); }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: 12px; }
.ref { color: var(--accent); border-bottom: 1px dashed #9fb4dd; }
.ref-unresolved { color: var(--ink-2); border-bottom: 1px dotted var(--amber); }
.note { font-family: var(--font-ui); font-size: 12px; color: var(--amber); }
@media (prefers-reduced-motion: reduce) { .btn { transition: none; } }
```

```tsx
// apps/web/src/app/layout.tsx
import type { Metadata } from "next";
import { IBM_Plex_Sans_KR, Noto_Serif_KR } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const ui = IBM_Plex_Sans_KR({ weight: ["400", "500", "600", "700"], subsets: ["latin"], variable: "--font-ui", display: "swap" });
const law = Noto_Serif_KR({ weight: ["400", "600"], subsets: ["latin"], variable: "--font-law", display: "swap" });

export const metadata: Metadata = { title: "NST 규정·법령", description: "국가과학기술연구회·출연연 내부규정과 관련 법령" };

const NAV = [
  { href: "/regulations", label: "규정" },
  { href: "/search", label: "검색" },
  { href: "/review", label: "검수" },
];

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko" className={`${ui.variable} ${law.variable}`}>
      <body className="min-h-screen font-sans antialiased">
        <header className="flex h-14 items-center gap-5 bg-[var(--ink)] px-6 text-white">
          <Link href="/regulations" className="flex items-center gap-2.5 whitespace-nowrap text-[15px] font-semibold text-white hover:no-underline">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
              <path d="M4 4h11l5 5v11H4z" /><path d="M15 4v5h5M8 13h8M8 17h5" />
            </svg>
            NST 규정·법령
          </Link>
          <nav className="flex gap-1" aria-label="주 메뉴">
            {NAV.map((n) => (
              <Link key={n.href} href={n.href} className="rounded-md px-3 py-2 text-sm text-[#c9ced6] hover:bg-[#262b32] hover:text-white hover:no-underline">
                {n.label}
              </Link>
            ))}
          </nav>
        </header>
        {children}
      </body>
    </html>
  );
}
```

```tsx
// apps/web/src/app/page.tsx
import { redirect } from "next/navigation";

export default function Home() {
  redirect("/regulations");
}
```

- [ ] **Step 4: 빌드 확인 후 커밋**

Run: `cd apps/web && npm install && npm run build`
Expected: 빌드가 성공하고 `public/pdf.worker.min.mjs`가 생긴다.

```bash
git add apps/web/package.json apps/web/package-lock.json apps/web/next.config.ts apps/web/src apps/web/public/pdf.worker.min.mjs
git commit -m "feat(web): app shell, design tokens, API client"
```

---

### Task 4: 웹 — 규정 목록과 조문 뷰어

**Files:**
- Create: `apps/web/src/app/regulations/page.tsx`, `apps/web/src/app/regulations/[...id]/page.tsx`, `apps/web/src/components/ProvisionText.tsx`, `apps/web/src/components/Relations.tsx`

**Interfaces:**
- `/regulations?inst=KASI&q=여비&kind=law`
  - 기관 칩(전체·기관별·법령)과 제목 검색을 둔다.
  - 규정 카드: 제목, 상태 칩, 시행일
- `/regulations/<id 세그먼트…>?as_of=YYYY-MM-DD&a=<path>`
  - 머리 카드
    - 제목, 원규분류
    - 칩: 상태, 시행일·근거, 개정번호, 출처, 검증
    - 기준일 입력(GET form), `연혁·비교`와 `원문 보기` 버튼
  - 3단 화면
    - 목차: 장과 조. `#path` 앵커로 이동한다.
    - 본문: 장 제목, 조(제목·본문), 항·호·목 들여쓰기, 주석, 부칙, 별표 원문
    - 오른쪽: 관계 패널(선택한 조 `a`가 없으면 첫 조), 연혁 목록, 열린 검수 작업
  - 본문의 참조 구간은 `ProvisionText`가 링크로 바꾼다.
    - 같은 문서 → `#path` (`a` 쿼리도 갱신)
    - 다른 work → `workHref(target)#path`
    - 미해석 → 점선 표시와 `title` 툴팁
- `Relations`(client): `fetch("/api/v1/references?pv=…")`로 나가는 참조와 들어오는 참조를 관계 유형 칩과 함께 보여준다.

- [ ] **Step 1: 구현**

```tsx
// apps/web/src/components/ProvisionText.tsx
import Link from "next/link";
import type { Ref } from "@/lib/api";
import { workHref } from "@/lib/api";
import { REL_LABEL } from "@/lib/format";

export function ProvisionText({ text, refs, workId }: { text: string; refs?: Ref[]; workId: string }) {
  if (!refs?.length) return <>{text}</>;
  const parts: React.ReactNode[] = [];
  let pos = 0;
  for (const [i, r] of refs.entries()) {
    if (r.start < pos || r.end > text.length) continue;
    parts.push(text.slice(pos, r.start));
    const seg = text.slice(r.start, r.end);
    const tip = `${REL_LABEL[r.rel_type] ?? r.rel_type}${r.target_name ? ` · ${r.target_name}` : ""}`;
    if (r.resolution === "RESOLVED" && r.target_work_id) {
      const hash = r.target_path ? `#${r.target_path}` : "";
      const href = r.target_work_id === workId ? `?a=${encodeURIComponent((r.target_path ?? "").split(".")[0])}${hash}`
        : workHref(r.target_work_id, hash);
      parts.push(<Link key={i} href={href} className="ref" title={tip}>{seg}</Link>);
    } else {
      parts.push(<span key={i} className="ref-unresolved" title={`${tip} · 대상 미확인`}>{seg}</span>);
    }
    pos = r.end;
  }
  parts.push(text.slice(pos));
  return <>{parts}</>;
}
```

```tsx
// apps/web/src/components/Relations.tsx
"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { workHref } from "@/lib/api";
import { REL_LABEL } from "@/lib/format";

type Out = { evidence_text: string; rel_type: string; target_work_id: string | null; target_path: string | null;
  target_name: string | null; target_title: string | null; resolution: string };
type In = { evidence_text: string; rel_type: string; source_work_id: string; source_title: string; source_path: string;
  source_label: string };

const CHIP: Record<string, string> = { EXCEPTION: "chip-amber", MUTATIS: "chip-blue", BASIS: "chip-blue", DELEGATION: "chip-blue" };

export function Relations({ pvId, label, workId }: { pvId: number; label: string; workId: string }) {
  const [data, setData] = useState<{ outgoing: Out[]; incoming: In[] } | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let alive = true;
    setData(null);
    fetch(`/api/v1/references?pv=${pvId}`).then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => alive && setData(d)).catch(() => alive && setError(true));
    return () => { alive = false; };
  }, [pvId]);
  return (
    <section className="card p-4" aria-live="polite">
      <h2 className="mb-3 text-[13px] font-semibold">{label}의 관계</h2>
      {error && <p className="text-[13px] text-[var(--muted)]">관계를 불러오지 못했습니다.</p>}
      {!data && !error && <p className="text-[13px] text-[var(--muted)]">불러오는 중…</p>}
      {data && data.outgoing.length + data.incoming.length === 0 && <p className="text-[13px] text-[var(--muted)]">연결된 조항이 없습니다.</p>}
      {data && (
        <ul className="flex flex-col gap-2.5 text-[13px]">
          {data.outgoing.map((r, i) => (
            <li key={`o${i}`} className="flex items-start gap-2.5">
              <span className={`chip shrink-0 ${CHIP[r.rel_type] ?? ""}`}>{REL_LABEL[r.rel_type] ?? r.rel_type}</span>
              <div>
                {r.target_work_id ? (
                  <Link href={r.target_work_id === workId ? `#${r.target_path ?? ""}` : workHref(r.target_work_id, r.target_path ? `#${r.target_path}` : "")}>
                    {r.target_work_id === workId ? r.evidence_text : `${r.target_title ?? r.target_name} ${r.target_path ?? ""}`}
                  </Link>
                ) : (
                  <span>{r.target_name ?? r.evidence_text}</span>
                )}
                {r.resolution !== "RESOLVED" && <div className="text-xs text-[var(--amber)]">대상 미해석 · 검수 대기</div>}
              </div>
            </li>
          ))}
          {data.incoming.map((r, i) => (
            <li key={`i${i}`} className="flex items-start gap-2.5">
              <span className="chip shrink-0">이 조항을 {REL_LABEL[r.rel_type] ?? r.rel_type}</span>
              <Link href={r.source_work_id === workId ? `#${r.source_path}` : workHref(r.source_work_id, `#${r.source_path}`)}>
                {r.source_work_id === workId ? r.source_path : `${r.source_title} ${r.source_path}`}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
```

```tsx
// apps/web/src/app/regulations/page.tsx
import Link from "next/link";
import { apiGet, type Institution, type Work, workHref } from "@/lib/api";
import { fmtDate, STATE_LABEL } from "@/lib/format";

export default async function RegulationsPage({ searchParams }: { searchParams: Promise<{ inst?: string; q?: string; kind?: string }> }) {
  const { inst, q, kind } = await searchParams;
  const [insts, works] = await Promise.all([
    apiGet<Institution[]>("/api/v1/institutions"),
    apiGet<Work[]>("/api/v1/works", { institution: inst, q, kind }),
  ]);
  const chip = (href: string, label: string, on: boolean) => (
    <Link key={href} href={href} className={`chip ${on ? "chip-blue" : ""}`}>{label}</Link>
  );
  return (
    <main className="mx-auto max-w-6xl px-6 py-6">
      <h1 className="mb-4 text-2xl font-bold">규정·법령</h1>
      <form className="mb-4 flex flex-wrap items-center gap-2" action="/regulations">
        {inst && <input type="hidden" name="inst" value={inst} />}
        <label htmlFor="q" className="sr-only">규정명</label>
        <input id="q" name="q" defaultValue={q} placeholder="규정명으로 찾기" className="h-9 w-72 rounded-lg border border-[var(--line-strong)] bg-white px-3 text-sm" />
        <button className="btn btn-dark" type="submit">찾기</button>
        <Link href={`/search${q ? `?q=${encodeURIComponent(q)}` : ""}`} className="btn">조문 내용 검색</Link>
      </form>
      <div className="mb-5 flex flex-wrap gap-2">
        {chip("/regulations", "전체", !inst && !kind)}
        {insts?.map((i) => chip(`/regulations?inst=${i.code}`, `${i.name} ${i.works}`, inst === i.code))}
        {chip("/regulations?kind=law", "법령", kind === "law")}
      </div>
      {!works?.length ? (
        <p className="card p-6 text-sm text-[var(--muted)]">해당하는 규정이 없습니다.</p>
      ) : (
        <ul className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {works.map((w) => (
            <li key={w.id}>
              <Link href={workHref(w.id)} className="card flex items-start justify-between gap-3 p-4 text-[var(--ink)] hover:no-underline hover:border-[var(--accent-line)]">
                <div>
                  <div className="font-semibold">{w.title}</div>
                  <div className="mt-1 text-xs text-[var(--muted)]">{w.institution ?? w.kind}</div>
                </div>
                {w.version && (
                  <div className="flex shrink-0 flex-col items-end gap-1 text-xs">
                    <span className={`chip ${w.version.version_state === "CURRENT" ? "chip-green" : "chip-amber"}`}>{STATE_LABEL[w.version.version_state]}</span>
                    <span className="text-[var(--muted)]">시행 {fmtDate(w.version.effective_from)}</span>
                  </div>
                )}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
```

```tsx
// apps/web/src/app/regulations/[...id]/page.tsx
import Link from "next/link";
import { notFound } from "next/navigation";
import { ProvisionText } from "@/components/ProvisionText";
import { Relations } from "@/components/Relations";
import { apiGet, decodeSegments, type Provision, type VersionRow, type ViewData, workHref } from "@/lib/api";
import { BASIS_LABEL, fmtDate, STATE_LABEL, STATUS_LABEL, TASK_LABEL } from "@/lib/format";

const INDENT: Record<string, string> = { paragraph: "", item: "pl-5", subitem: "pl-10" };

export default async function ViewerPage({ params, searchParams }: {
  params: Promise<{ id: string[] }>; searchParams: Promise<{ as_of?: string; a?: string }>;
}) {
  const { id } = await params;
  const { as_of, a } = await searchParams;
  const workId = decodeSegments(id);
  const [view, versions] = await Promise.all([
    apiGet<ViewData>("/api/v1/work/view", { id: workId, as_of }),
    apiGet<VersionRow[]>("/api/v1/work/versions", { id: workId }),
  ]);
  if (!versions) notFound();
  if (!view) {
    return (
      <main className="mx-auto max-w-3xl px-6 py-10">
        <p className="card p-6">{fmtDate(as_of ?? null)}에 시행 중인 버전이 없습니다. <Link href={workHref(workId)}>현행 보기</Link></p>
      </main>
    );
  }
  const { work, version: v, provisions, refs, history, tasks } = view;
  const articles = provisions.filter((p) => p.unit === "article");
  const selected = articles.find((p) => p.path === a) ?? articles[0];
  const tops = provisions.filter((p) => ["chapter", "section", "article", "supplement", "annex"].includes(p.unit));
  const kids = (path: string): Provision[] => provisions.filter((p) => p.parent === path);
  const subtree = (path: string): Provision[] => kids(path).flatMap((k) => [k, ...subtree(k.path)]);
  const isLaw = work.id.startsWith("kr/law/");

  return (
    <main className="pb-8">
      <div className="flex flex-wrap items-center gap-1.5 px-6 pt-4 text-[13px] text-[var(--muted)]">
        <Link href={work.institution ? `/regulations?inst=${work.institution}` : "/regulations?kind=law"}>{work.institution ?? "법령"}</Link>
        <span>/</span><span className="text-[var(--ink)]">{work.title}</span>
      </div>
      <section className="card mx-6 mt-3 flex flex-wrap items-end gap-6 px-6 py-5">
        <div className="flex grow flex-col gap-2.5">
          <div className="flex flex-wrap items-baseline gap-3">
            <h1 className="text-[26px] font-bold tracking-tight">{v.title}</h1>
            {v.class_code && <span className="font-mono text-xs text-[var(--muted)]">원규분류 {v.class_code}</span>}
          </div>
          <div className="flex flex-wrap gap-2">
            <span className={`chip ${v.version_state === "CURRENT" ? "chip-green" : "chip-amber"}`}>{STATE_LABEL[v.version_state]}</span>
            <span className="chip">시행 {fmtDate(v.effective_from)} · {BASIS_LABEL[v.effective_basis]}</span>
            {v.effective_status !== "CONFIRMED" && <span className="chip chip-amber">{STATUS_LABEL[v.effective_status]}</span>}
            {v.amendment_no && <span className="chip">{v.amendment_kind ?? "개정"} · 제{v.amendment_no}호</span>}
            <span className="chip">출처 {isLaw ? "law.go.kr" : "ALIO"}</span>
            <span className={`chip ${v.validation_status === "PASSED" ? "chip-blue" : "chip-amber"}`}>{v.validation_status === "PASSED" ? "검증 통과" : "검수 필요"}</span>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <form className="flex items-center gap-2 text-[13px] text-[var(--ink-2)]">
            <label htmlFor="as_of">기준일</label>
            <input id="as_of" name="as_of" type="date" defaultValue={as_of} className="h-9 rounded-lg border border-[var(--line-strong)] px-2.5" />
            <button className="btn" type="submit">보기</button>
          </form>
          <Link className="btn" href={`/compare?work=${encodeURIComponent(work.id)}`}>연혁·비교</Link>
          {isLaw ? (
            <a className="btn btn-dark" href={v.source.url.replace("type=XML", "type=HTML")} target="_blank" rel="noreferrer">law.go.kr 원문</a>
          ) : (
            <Link className="btn btn-dark" href={workHref(work.id, `/source?version=${encodeURIComponent(v.id)}${selected ? `&a=${selected.path}` : ""}`)}>원문 보기</Link>
          )}
        </div>
      </section>

      <div className="grid grid-cols-1 gap-4 px-6 pt-4 lg:grid-cols-[240px_minmax(0,1fr)_340px]">
        <nav aria-label="목차" className="card hidden self-start p-2 text-[13px] lg:block lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:overflow-auto">
          <div className="px-2.5 pb-2 text-xs font-semibold text-[var(--muted)]">목차</div>
          {tops.map((p) => (
            <a key={p.path} href={`?${new URLSearchParams({ ...(as_of ? { as_of } : {}), ...(p.unit === "article" ? { a: p.path } : {}) })}#${p.path}`}
              className={`block rounded-md px-2.5 py-1 text-[var(--ink-2)] hover:bg-[#ebeef2] hover:no-underline ${p.unit === "article" ? "pl-5" : "font-semibold"} ${p.path === selected?.path ? "bg-[var(--accent-soft)] text-[var(--accent)]" : ""}`}>
              {p.label}{p.heading ? ` ${p.heading}` : ""}
            </a>
          ))}
        </nav>

        <article className="card px-6 py-7 font-serif text-base leading-[1.85] md:px-9">
          {tops.map((p) => {
            if (p.unit === "chapter" || p.unit === "section") {
              return <h2 key={p.path} id={p.path} className="mb-4 mt-6 text-center font-sans text-[15px] font-semibold tracking-[0.2em] text-[var(--muted)] first:mt-0">{p.label} {p.heading}</h2>;
            }
            const on = p.path === selected?.path;
            return (
              <section key={p.path} id={p.path} className={`scroll-mt-4 py-3 ${on ? "-mx-4 rounded-xl bg-[#f5f8fe] px-4 outline outline-1 outline-[var(--accent-line)]" : ""}`}>
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <div className="font-semibold">{p.label}{p.heading ? `(${p.heading})` : ""}</div>
                  {p.unit === "article" && !on && (
                    <a className="font-sans text-xs" href={`?${new URLSearchParams({ ...(as_of ? { as_of } : {}), a: p.path })}#${p.path}`}>관계 보기</a>
                  )}
                </div>
                {p.text && <p className={`mt-1 ${p.deleted ? "text-[var(--muted)]" : ""}`}><ProvisionText text={p.text} refs={refs[String(p.id)]} workId={work.id} /></p>}
                {subtree(p.path).map((c) => (
                  <p key={c.path} id={c.path} className={`mt-1.5 ${INDENT[c.unit] ?? ""} ${c.deleted ? "text-[var(--muted)]" : ""}`}>
                    {c.unit !== "supp_article" ? `${c.label} ` : <strong className="font-semibold">{c.label}{c.heading ? `(${c.heading}) ` : " "}</strong>}
                    <ProvisionText text={c.text} refs={refs[String(c.id)]} workId={work.id} />
                    {c.annotations.map((n) => <span key={n} className="note"> {n}</span>)}
                  </p>
                ))}
                {p.annotations.length > 0 && <div className="mt-1 font-sans text-xs text-[var(--muted)]">{p.annotations.join(" ")}</div>}
              </section>
            );
          })}
        </article>

        <aside className="flex flex-col gap-4 self-start">
          {selected && <Relations pvId={selected.id} label={`${selected.label}`} workId={work.id} />}
          <section className="card p-4">
            <div className="mb-3 flex items-baseline justify-between">
              <h2 className="text-[13px] font-semibold">연혁</h2>
              <Link className="text-xs" href={`/compare?work=${encodeURIComponent(work.id)}`}>버전 비교</Link>
            </div>
            <ol className="flex flex-col gap-2 text-[13px]">
              {versions.slice(0, 8).map((x) => (
                <li key={x.id} className="flex justify-between gap-2">
                  {x.id === v.id ? <span className="font-semibold">{fmtDate(x.effective_from)} 시행</span>
                    : <Link href={x.effective_from ? `?as_of=${x.effective_from}` : "#"}>{fmtDate(x.effective_from)} 시행</Link>}
                  <span className="text-[var(--muted)]">{x.amendment_no ? `제${x.amendment_no}호 · ` : ""}{STATE_LABEL[x.version_state]}</span>
                </li>
              ))}
            </ol>
            {history.length > 0 && <p className="mt-3 text-xs text-[var(--muted)]">제정 {fmtDate(history[0].date)} · 개정 이력 {history.length}건</p>}
          </section>
          {tasks.length > 0 && (
            <section className="card p-4 text-[13px]">
              <h2 className="mb-2 font-semibold">검수 대기</h2>
              <ul className="flex flex-col gap-1">{tasks.map((t, i) => <li key={i}><span className="chip chip-amber">{TASK_LABEL[t.kind]}</span></li>)}</ul>
            </section>
          )}
        </aside>
      </div>
    </main>
  );
}
```

- [ ] **Step 2: 빌드 확인 후 커밋**

Run: `cd apps/web && npm run build` → 성공

```bash
git add apps/web/src
git commit -m "feat(web): regulation list and law.go.kr-style provision viewer with relations"
```

---

### Task 5: 웹 — 원문 대조, 신구 비교, 검색, 검수 큐

**Files:**
- Create: `apps/web/src/components/PdfPane.tsx`, `apps/web/src/app/regulations/[...id]/source/page.tsx`, `apps/web/src/app/compare/page.tsx`, `apps/web/src/app/search/page.tsx`, `apps/web/src/app/review/page.tsx`

**Interfaces:**
- `PdfPane`(client) `{ fileUrl: string; page: number; bbox: [number, number, number, number] | null; label: string }`
  - react-pdf로 해당 쪽을 그린다. worker는 `/pdf.worker.min.mjs`를 쓴다.
  - `bbox`(PDF 포인트, 왼쪽 위 원점)를 화면 배율에 맞춰 노란 강조 박스로 덧그린다.
  - 이전 쪽·다음 쪽 버튼을 둔다.
- `/regulations/<id>/source?version=&a=`
  - 왼쪽: 조문 목록. 쪽 번호를 함께 보여주고, 누르면 `?a=`로 이동한다.
  - 오른쪽: `PdfPane`
  - 보기용 PDF가 없으면(`has_view=false`) 안내 문구와 원본 다운로드 링크를 보여준다.
- `/compare?work=&from=&to=`
  - 버전 두 개를 고르는 GET form. 기본값은 직전 버전과 최신 버전이다.
  - 변경 목록을 구·신 2열 표로 보여주고, 신설·삭제 칸은 빗금 처리한다.
- `/search?q=&inst=`: 결과 목록. 누르면 뷰어의 `?a=조#path`로 이동한다.
- `/review?kind=`: 열린 검수 작업 표(종류, 규정, 내용, 생성일)

- [ ] **Step 1: 구현**

```tsx
// apps/web/src/components/PdfPane.tsx
"use client";

import { useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/TextLayer.css";

pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";

export function PdfPane({ fileUrl, page, bbox, label }: {
  fileUrl: string; page: number; bbox: [number, number, number, number] | null; label: string;
}) {
  const [cur, setCur] = useState(page);
  const [pages, setPages] = useState(0);
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  const width = 640;
  const scale = size ? width / size.w : 1;
  return (
    <section className="flex flex-col overflow-hidden rounded-xl bg-[#2a2f36]">
      <div className="flex items-center gap-2 bg-[#20242a] px-3 py-2.5 text-[13px] text-[#e3e7ec]">
        <span className="truncate">{label}</span>
        <div className="ml-auto flex items-center gap-1.5">
          <button className="btn h-9 w-9 justify-center border-[#444b54] bg-[#343a42] px-0 text-white" aria-label="이전 쪽" disabled={cur <= 1} onClick={() => setCur((c) => c - 1)}>‹</button>
          <span className="min-w-16 text-center">{cur} / {pages || "?"}</span>
          <button className="btn h-9 w-9 justify-center border-[#444b54] bg-[#343a42] px-0 text-white" aria-label="다음 쪽" disabled={pages > 0 && cur >= pages} onClick={() => setCur((c) => c + 1)}>›</button>
          <a className="btn border-[#e3e7ec] bg-[#e3e7ec] text-[var(--ink)]" href={fileUrl} target="_blank" rel="noreferrer">PDF 열기</a>
        </div>
      </div>
      <div className="flex justify-center overflow-auto p-6">
        <Document file={fileUrl} onLoadSuccess={(d) => setPages(d.numPages)} loading={<p className="text-sm text-[#c9ced6]">문서를 불러오는 중…</p>}
          error={<p className="text-sm text-[#c9ced6]">문서를 불러오지 못했습니다.</p>}>
          <div className="relative shadow-[0_2px_10px_rgba(0,0,0,0.35)]">
            <Page pageNumber={cur} width={width} renderAnnotationLayer={false}
              onLoadSuccess={(p) => setSize({ w: p.originalWidth, h: p.originalHeight })} />
            {bbox && cur === page && size && (
              <div aria-hidden="true" className="pointer-events-none absolute rounded-[3px] bg-[#fff1a8]/50 ring-2 ring-[#e2b400]"
                style={{ left: bbox[0] * scale - 4, top: bbox[1] * scale - 3, width: (bbox[2] - bbox[0]) * scale + 8, height: (bbox[3] - bbox[1]) * scale + 6 }} />
            )}
          </div>
        </Document>
      </div>
    </section>
  );
}
```

```tsx
// apps/web/src/app/regulations/[...id]/source/page.tsx
import Link from "next/link";
import { notFound } from "next/navigation";
import { PdfPane } from "@/components/PdfPane";
import { apiGet, decodeSegments, type ViewData, workHref } from "@/lib/api";
import { fmtDate } from "@/lib/format";

export default async function SourcePage({ params, searchParams }: {
  params: Promise<{ id: string[] }>; searchParams: Promise<{ version?: string; a?: string; as_of?: string }>;
}) {
  const { id } = await params;
  const { a, as_of } = await searchParams;
  const workId = decodeSegments(id);
  const view = await apiGet<ViewData>("/api/v1/work/view", { id: workId, as_of });
  if (!view) notFound();
  const { work, version: v, provisions } = view;
  const arts = provisions.filter((p) => ["article", "supplement", "annex"].includes(p.unit));
  const sel = arts.find((p) => p.path === a) ?? arts.find((p) => p.anchor) ?? arts[0];
  const fileUrl = `/api/v1/file?version=${encodeURIComponent(v.id)}&kind=view`;
  const original = `/api/v1/file?version=${encodeURIComponent(v.id)}&kind=original`;
  return (
    <main className="pb-8">
      <div className="flex flex-wrap items-center gap-3 px-6 py-3.5">
        <Link className="btn" href={workHref(work.id, sel ? `?a=${sel.path}#${sel.path}` : "")}>← 조문 보기</Link>
        <h1 className="text-[17px] font-bold">{work.title} · 원문 대조</h1>
        <span className="chip">{fmtDate(v.effective_from)} 시행본</span>
        <a className="text-[13px]" href={original}>원본 내려받기{v.source.file_name ? ` (${v.source.file_name})` : ""}</a>
      </div>
      <div className="grid grid-cols-1 gap-4 px-6 lg:grid-cols-[380px_minmax(0,1fr)]">
        <nav aria-label="조문 위치" className="card flex max-h-[calc(100vh-9rem)] flex-col gap-0.5 self-start overflow-auto p-2">
          {arts.map((p) => (
            <Link key={p.path} href={`?${new URLSearchParams({ a: p.path, ...(as_of ? { as_of } : {}) })}`}
              className={`flex justify-between gap-2 rounded-lg px-3 py-2 text-[13px] text-[var(--ink-2)] hover:bg-[#ebeef2] hover:no-underline ${p.path === sel?.path ? "bg-[var(--accent-soft)] text-[var(--accent)]" : ""}`}>
              <span><span className="font-medium">{p.label}</span> {p.heading}</span>
              <span className="text-[var(--muted)]">{p.anchor ? `${p.anchor.page}쪽` : "-"}</span>
            </Link>
          ))}
        </nav>
        {v.source.has_view && sel?.anchor ? (
          <PdfPane key={`${v.id}-${sel.path}`} fileUrl={fileUrl} page={sel.anchor.page} bbox={sel.anchor.bbox} label={v.source.file_name ?? v.title} />
        ) : v.source.has_view ? (
          <PdfPane key={v.id} fileUrl={fileUrl} page={1} bbox={null} label={v.source.file_name ?? v.title} />
        ) : (
          <div className="card p-6 text-sm">
            이 버전은 보기용 PDF가 없습니다({v.source.view_status === "failed" ? "변환 실패" : "준비 전"}). <a href={original}>원본 파일 내려받기</a>
          </div>
        )}
      </div>
    </main>
  );
}
```

```tsx
// apps/web/src/app/compare/page.tsx
import Link from "next/link";
import { apiGet, type DiffData, type VersionRow, workHref } from "@/lib/api";
import { CHANGE_LABEL, fmtDate } from "@/lib/format";

export default async function ComparePage({ searchParams }: { searchParams: Promise<{ work?: string; from?: string; to?: string }> }) {
  const { work, from, to } = await searchParams;
  if (!work) return <main className="mx-auto max-w-3xl px-6 py-10"><p className="card p-6">비교할 규정을 먼저 고르세요. <Link href="/regulations">규정 목록</Link></p></main>;
  const versions = (await apiGet<VersionRow[]>("/api/v1/work/versions", { id: work })) ?? [];
  const toId = to ?? versions[0]?.id;
  const fromId = from ?? versions[1]?.id;
  const diff = fromId && toId ? await apiGet<DiffData>("/api/v1/diff", { from: fromId, to: toId }) : null;
  const sel = (name: string, value: string | undefined) => (
    <select name={name} defaultValue={value} className="h-9 rounded-lg border border-[var(--line-strong)] bg-white px-2 text-[13px]">
      {versions.map((v) => <option key={v.id} value={v.id}>{fmtDate(v.effective_from)} 시행{v.amendment_no ? ` · 제${v.amendment_no}호` : ""}</option>)}
    </select>
  );
  return (
    <main className="px-6 py-4">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Link className="btn" href={workHref(work)}>← 조문 보기</Link>
        <h1 className="text-[17px] font-bold">연혁과 신구 비교</h1>
      </div>
      {versions.length < 2 ? <p className="card p-6 text-sm">비교할 버전이 하나뿐입니다.</p> : (
        <>
          <form className="card mb-4 flex flex-wrap items-center gap-2 px-4 py-3 text-[13px]">
            <input type="hidden" name="work" value={work} />
            <label>구 {sel("from", fromId)}</label><span>→</span><label>신 {sel("to", toId)}</label>
            <button className="btn btn-dark" type="submit">비교</button>
            {diff && <span className="ml-auto text-[var(--muted)]">변경 {diff.changes.length}건</span>}
          </form>
          {diff && (
            <div className="card overflow-hidden">
              <div className="grid grid-cols-2 border-b border-[var(--line)] bg-[#f7f8fa] text-xs font-semibold text-[var(--muted)]">
                <div className="border-r border-[var(--line)] px-4 py-2.5">구 · {fmtDate(diff.from.effective_from)} 시행</div>
                <div className="px-4 py-2.5">신 · {fmtDate(diff.to.effective_from)} 시행</div>
              </div>
              {diff.changes.length === 0 && <p className="p-6 text-sm">달라진 조항이 없습니다.</p>}
              {diff.changes.map((c) => (
                <div key={c.provision_id} className="grid grid-cols-2 border-b border-[var(--line)] font-serif text-[15px] leading-[1.8] last:border-b-0">
                  {[c.from, c.to].map((s, i) => (
                    <div key={i} className={`px-4 py-3 ${i === 0 ? "border-r border-[var(--line)]" : ""} ${!s ? "bg-[repeating-linear-gradient(135deg,#fafbfc_0_8px,#f3f5f8_8px_16px)]" : i === 1 ? "bg-[#eef7f0]" : ""}`}>
                      {i === 1 && <span className="chip chip-green mb-1 font-sans">{CHANGE_LABEL[c.kind]}</span>}
                      {s ? <><div className="font-semibold">{s.label}{s.heading ? `(${s.heading})` : ""}</div><p>{s.text}</p></>
                        : <p className="font-sans text-[13px] text-[var(--muted)]">〈{i === 0 ? "신설" : "삭제"}〉</p>}
                    </div>
                  ))}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </main>
  );
}
```

```tsx
// apps/web/src/app/search/page.tsx
import Link from "next/link";
import { apiGet, type Institution, type SearchHit, workHref } from "@/lib/api";

export default async function SearchPage({ searchParams }: { searchParams: Promise<{ q?: string; inst?: string }> }) {
  const { q, inst } = await searchParams;
  const insts = await apiGet<Institution[]>("/api/v1/institutions");
  const hits = q && q.trim().length >= 2 ? await apiGet<SearchHit[]>("/api/v1/search", { q: q.trim(), institution: inst }) : null;
  return (
    <main className="mx-auto max-w-4xl px-6 py-6">
      <h1 className="mb-4 text-2xl font-bold">조문 검색</h1>
      <form className="mb-5 flex flex-wrap gap-2">
        <label htmlFor="sq" className="sr-only">검색어</label>
        <input id="sq" name="q" defaultValue={q} placeholder="예: 7일 이내, 숙박비" className="h-10 w-80 rounded-lg border border-[var(--line-strong)] bg-white px-3" />
        <label htmlFor="si" className="sr-only">기관</label>
        <select id="si" name="inst" defaultValue={inst ?? ""} className="h-10 rounded-lg border border-[var(--line-strong)] bg-white px-2 text-sm">
          <option value="">전체 기관</option>
          {insts?.map((i) => <option key={i.code} value={i.code}>{i.name}</option>)}
        </select>
        <button className="btn btn-dark h-10" type="submit">검색</button>
      </form>
      {q && q.trim().length < 2 && <p className="text-sm text-[var(--muted)]">두 글자 이상 입력하세요.</p>}
      {hits && (hits.length === 0 ? <p className="card p-6 text-sm">찾는 조문이 없습니다.</p> : (
        <ul className="flex flex-col gap-2">
          {hits.map((h, i) => {
            const art = h.path.split(".")[0];
            return (
              <li key={i} className="card p-4">
                <Link href={workHref(h.work_id, `?a=${art}#${h.path}`)} className="font-semibold">{h.title} {h.label}{h.heading ? `(${h.heading})` : ""}</Link>
                <span className="ml-2 text-xs text-[var(--muted)]">{h.institution ?? "법령"}</span>
                <p className="mt-1 font-serif text-[15px] leading-relaxed">{h.snippet}</p>
              </li>
            );
          })}
        </ul>
      ))}
    </main>
  );
}
```

```tsx
// apps/web/src/app/review/page.tsx
import Link from "next/link";
import { apiGet, type ReviewTask, workHref } from "@/lib/api";
import { fmtDate, TASK_LABEL } from "@/lib/format";

export default async function ReviewPage({ searchParams }: { searchParams: Promise<{ kind?: string }> }) {
  const { kind } = await searchParams;
  const tasks = (await apiGet<ReviewTask[]>("/api/v1/review-tasks", { status: "OPEN", kind })) ?? [];
  return (
    <main className="mx-auto max-w-6xl px-6 py-6">
      <h1 className="mb-1 text-2xl font-bold">검수 큐</h1>
      <p className="mb-4 text-[13px] text-[var(--muted)]">자동 판정이 불확실한 항목입니다. 처리(승인·수정)는 로그인 기능과 함께 제공됩니다.</p>
      <div className="mb-4 flex flex-wrap gap-2">
        <Link href="/review" className={`chip ${!kind ? "chip-blue" : ""}`}>전체</Link>
        {Object.entries(TASK_LABEL).map(([k, l]) => <Link key={k} href={`/review?kind=${k}`} className={`chip ${kind === k ? "chip-blue" : ""}`}>{l}</Link>)}
      </div>
      {tasks.length === 0 ? <p className="card p-6 text-sm">열린 검수 작업이 없습니다.</p> : (
        <table className="card w-full overflow-hidden text-[13px]">
          <thead className="bg-[#f7f8fa] text-left text-xs text-[var(--muted)]">
            <tr><th className="px-4 py-2.5">유형</th><th className="px-4 py-2.5">규정</th><th className="px-4 py-2.5">내용</th><th className="px-4 py-2.5">생성</th></tr>
          </thead>
          <tbody>
            {tasks.map((t) => (
              <tr key={t.id} className="border-t border-[var(--line)] align-top">
                <td className="px-4 py-2.5"><span className="chip chip-amber">{TASK_LABEL[t.kind] ?? t.kind}</span></td>
                <td className="px-4 py-2.5">{t.work_id ? <Link href={workHref(t.work_id)}>{t.work_title}</Link> : "-"}</td>
                <td className="px-4 py-2.5 font-mono text-xs text-[var(--ink-2)]">{JSON.stringify(t.detail)}</td>
                <td className="px-4 py-2.5 whitespace-nowrap text-[var(--muted)]">{fmtDate(t.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
```

- [ ] **Step 2: 빌드 확인 후 커밋**

Run: `cd apps/web && npm run build` → 성공. 타입 오류가 없어야 한다.

```bash
git add apps/web/src
git commit -m "feat(web): source comparison with PDF highlight, version diff, search, review queue"
```

---

### Task 6: 실행 스크립트와 실데이터 확인

**Files:**
- Create: `scripts/run-dev.sh`
- Modify: `README.md`

- [ ] **Step 1: 실행 스크립트**

```bash
#!/usr/bin/env bash
# API(:21061)와 웹(:21060)을 백그라운드로 띄운다. 로그: .run/*.log
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p .run
set -a; . ./.env; set +a
pkill -f "reg api" 2>/dev/null || true
pkill -f "next start -p 21060" 2>/dev/null || true
nohup uv run reg api --host 0.0.0.0 --port 21061 > .run/api.log 2>&1 &
(cd apps/web && npm run build > ../../.run/web-build.log 2>&1 && nohup npm run start > ../../.run/web.log 2>&1 &)
for i in $(seq 1 60); do curl -sf localhost:21061/api/v1/institutions >/dev/null && curl -sf localhost:21060/regulations >/dev/null && break; sleep 2; done
echo "API  http://$(hostname -I | awk '{print $1}'):21061/docs"
echo "WEB  http://$(hostname -I | awk '{print $1}'):21060/regulations"
```

`.gitignore`에 `.run/`를 추가한다.

- [ ] **Step 2: 실행과 확인**

```bash
bash scripts/run-dev.sh
curl -s "localhost:21060/regulations?inst=KASI" | grep -c "여비규정"
curl -s "localhost:21060/regulations/kr/reg/KASI/%EC%97%AC%EB%B9%84%EA%B7%9C%EC%A0%95?a=a27" | grep -c "7일 이내"
curl -s "localhost:21060/search?q=7%EC%9D%BC%20%EC%9D%B4%EB%82%B4" | grep -c "제27조"
curl -s -o /dev/null -w "%{http_code}\n" "localhost:21060/review"
```

Expected: 앞의 세 명령은 1 이상을 출력하고, 마지막 명령은 200을 출력한다.

- [ ] **Step 3: README 갱신과 커밋**

README에 "화면 실행" 절을 추가한다. 내용은 `bash scripts/run-dev.sh`와 접속 주소다.

```bash
git add scripts/run-dev.sh README.md .gitignore
git commit -m "chore: dev run script for API and web"
```

---

## Self-Review 결과

**스펙 대응 (spec 10절 화면)**

| 화면 | 반영 위치 |
|---|---|
| 기관·규정 목록 | Task 4 |
| 규정 뷰어 | Task 4 |
| 원문 대조 | Task 5 |
| 버전·비교 | Task 5 |
| 검수 큐 (읽기 전용, 결정은 M5) | Task 5 |
| 키워드 검색 (M4에서 하이브리드로 교체) | Task 2, 5 |
| NFR-02 LLM 없이 열람 | 전체 |

질의응답·개정 알림 화면은 M4·M5 범위다.

**타입 일치**: API 응답 키와 `api.ts` 타입 이름이 같다.
- `label`(`number_label` 별칭), `anchor`(`source_anchor` 별칭), `parent`(`parent_path` 별칭)
- `refs`의 키는 문자열 pv id다.

**Review Focus**
- 1: `test_view_current_with_refs_and_unicode_id`와 Task 6의 curl 확인이 다룬다.
- 2·3: Task 1 테스트와 뷰어의 404 화면이 다룬다.
- 4: `has_view` 분기가 다룬다.
- 5: `test_search_escapes_wildcards`가 다룬다.
