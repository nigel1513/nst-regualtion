# M5a 개정 감지·영향 분석·담당자 알림 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 법령이나 모규정에 새 버전이 들어오면, 그 버전에서 실질적으로 바뀐 조항을 확정한다. 이어서 그 조항을 근거·위임·준용·참조하는 다른 규정의 조항을 찾아 영향 유형과 심각도를 판정하고, 규정별 담당자에게 알림(앱 내 알림 + 메일)을 보낸다. 이 경로는 질의응답과 독립적으로 동작한다(spec 9).

과거 버전 이력으로 같은 과정을 다시 돌려 영향 탐지 결과를 사후 검증한다(spec 12).

**Architecture:**
- **Neo4j(그래프 투영)**
  - 현행 버전의 규범문서·조항·참조를 PostgreSQL에서 Neo4j로 옮긴다(`reg graph sync`, 전체 재투영, 멱등).
  - 영향 탐색은 Cypher로 참조를 역방향으로 따라간다. 직접 참조와, 위임 사슬을 통한 2단계까지 본다.
- **개정 이벤트**
  - 처리기가 이미 버전이 있던 규범문서에 더 최신 버전을 붙이면 outbox `regulation.version_loaded`를 남긴다.
  - 처음 적재할 때(그 규범문서의 첫 묶음)는 남기지 않는다.
- **영향 분석·알림** (`reg.alerts`)
  - 이벤트를 소비해 `change_impact`를 만든다(`reg alerts scan`).
  - 담당자별 알림과 메일을 만든다(`reg alerts notify`). 심각도 높음은 즉시, 그 밖에는 하루 묶음으로 보낸다.
- **API·웹**: 개정 알림함(시안 `docs/ui/Alerts.dc.html`). 상태 변경은 M5b(로그인) 전까지 내부망 전제로 둔다.

**Tech Stack:**
- Neo4j 5.26 Community(공식 Python 드라이버 `neo4j`)
- SMTP(개발: 공유 Mailpit, 중계 `127.0.0.1:21068`)

**Spec:** `docs/superpowers/specs/2026-10-01-regulation-platform-design.md` (5.5 Neo4j, 9 개정 감지·영향·알림, 12 사후 검증)

## Global Constraints

- **Neo4j**
  - 접속: `bolt://127.0.0.1:21064`(http 21065), 계정 `neo4j`, 비밀번호는 `.env`의 `REG_NEO4J_PASSWORD`
  - 라벨 접두어는 `Reg`다. 다른 라벨은 건드리지 않는다.
- **관계 타입**: `BASIS|DELEGATION|IMPLEMENTS|MUTATIS|EXCEPTION|CITATION` (spec 5.1)
  - 관계 속성: `evidence`, `source_path`, `resolution`, `review_status`
- **심각도 (spec 9.2-3)**

  | 원인 변경 | 참조 관계 | 심각도 |
  |---|---|---|
  | 대상 조항 DELETED | 모든 관계 | HIGH |
  | MODIFIED | BASIS, DELEGATION, MUTATIS, IMPLEMENTS | HIGH |
  | MODIFIED | CITATION, EXCEPTION | MEDIUM |
  | RENUMBERED | 모든 관계 (참조 번호를 고쳐야 함) | MEDIUM |
  | ADDED | 규범문서 전체(WORK)를 참조하는 규정만 | LOW |

- **알림 수신자**
  - 1순위: `owner_assignment`의 담당자
  - 담당자가 없으면 `config/admins.yaml`에 적힌 기관 관리자
  - 둘 다 없으면 수신자 없이 알림함에만 남는다.
- **멱등성**
  - `change_impact`는 `(cause_version_id, cause_path, affected_work_id, affected_path)`가 유일하다.
  - `notification`은 `(impact_id, recipient)`가 유일하다.

## Review Focus

1. **처음 적재(백필)할 때 알림 폭주.** 그 규범문서의 첫 묶음이면 이벤트를 만들지 않아야 한다. Task 4에서 테스트한다.
2. **주석만 바뀐 개정(ANNOTATION_ONLY).** 영향이 생기면 안 된다. Task 3에서 테스트한다.
3. **같은 규범문서 안의 참조.** 다른 규정에 대한 영향으로 세지 않는다. Task 3에서 테스트한다.
4. **같은 개정을 다시 스캔할 때.** 영향과 알림이 중복되면 안 된다. Task 3, 5에서 테스트한다.
5. **Neo4j가 꺼져 있을 때 스캔.** 이벤트를 실패로 남기고 재시도해야 한다. 처리 완료로 표시하면 안 된다. Task 4에서 테스트한다.

---

## File Structure

```
infra/docker-compose.yml               # (수정) neo4j, mailpit-proxy
config/admins.yaml                     # 기관별 관리자 메일 (알림 기본 수신자)
src/reg/settings.py                    # (수정) neo4j_url/user/password, smtp_host/port/from
src/reg/migrations/versions/0007_alerts.py
src/reg/graph/__init__.py
src/reg/graph/sync.py                  # sync_graph(conn, driver) -> dict
src/reg/alerts/__init__.py
src/reg/alerts/impact.py               # SEVERITY, analyze_version(conn, driver, work_id, version_id) -> list[dict]
src/reg/alerts/scan.py                 # scan_once(conn, driver) — version_loaded 소비
src/reg/alerts/notify.py               # build_notifications(conn), send_due(conn, mailer, now) ; SmtpMailer
src/reg/alerts/backtest.py             # backtest(conn, driver, limit) — 과거 개정 재생
src/reg/process.py                     # (수정) version_loaded 이벤트
src/reg/api/app.py                     # (수정) /api/v1/alerts…
src/reg/cli.py                         # (수정) reg graph sync, reg alerts scan|notify|backtest, reg owners import
apps/web/src/app/alerts/page.tsx       # 개정 알림함
tests/test_graph.py tests/test_impact.py tests/test_scan.py tests/test_notify.py tests/test_alerts_api.py
```

---

### Task 1: 인프라·설정·0007 마이그레이션

**Files:**
- Modify: `infra/docker-compose.yml`, `src/reg/settings.py`, `.env.example`, `pyproject.toml`(`neo4j>=5.20`), `tests/conftest.py`
  - conftest: TRUNCATE에 새 테이블을 추가하고, `neo4j_driver` 세션 픽스처를 만든다. testcontainers `DockerContainer("neo4j:5.26-community")`, `NEO4J_AUTH=neo4j/testpass1234`, 7687 포트를 쓰고 bolt 접속이 될 때까지 최대 90초 기다린다.
- Create: `src/reg/migrations/versions/0007_alerts.py`, `config/admins.yaml`, `tests/test_migrations_0007.py`

**Interfaces:**
- compose 서비스
  - `neo4j`: `neo4j:5.26-community`, ports `127.0.0.1:21064:7687`, `127.0.0.1:21065:7474`, env `NEO4J_AUTH=neo4j/${REG_NEO4J_PASSWORD}`, volume `neo4j-data`
  - `mailpit-proxy`: socat `127.0.0.1:21068` → `mailpit:1025`, nais 네트워크
- Settings
  - `neo4j_url="bolt://127.0.0.1:21064"`, `neo4j_user="neo4j"`, `neo4j_password=""`
  - `smtp_host="127.0.0.1"`, `smtp_port=21068`, `smtp_from="NST 규정·법령 <no-reply@nst-regulation.local>"`
- 0007 테이블
  - `change_impact`
    - 식별: `id`
    - 원인: `cause_work_id`, `cause_version_id`, `cause_from_version_id`, `cause_path`, `cause_change`(ADDED|MODIFIED|DELETED|RENUMBERED)
    - 영향 대상: `affected_work_id`, `affected_version_id`, `affected_path`, `rel_type`, `evidence`
    - 판정: `impact_kind`, `severity`(HIGH|MEDIUM|LOW), `hops`(1|2)
    - 처리: `status`(NEW|ACKED|ACTION_REQUIRED|NO_ACTION|RESOLVED) 기본 NEW, `resolution_note`, `resolved_by_version_id`, `created_at`, `updated_at`
    - UNIQUE(`cause_version_id`, `cause_path`, `affected_work_id`, `affected_path`)
  - `owner_assignment`: `id`, `work_id`, `email`, `name`, `org_unit`, `role`(OWNER|DEPUTY), UNIQUE(`work_id`, `email`)
  - `notification`: `id`, `impact_id`, `recipient`, `channel`(inapp|email), `severity`, `created_at`, `read_at`, `sent_at`, UNIQUE(`impact_id`, `recipient`)
  - `email_delivery`: `id`, `recipient`, `subject`, `body`, `notification_ids` bigint[], `status`(pending|sent|failed), `attempts`, `last_error`, `created_at`, `sent_at`

- [ ] **Step 1: 실패하는 테스트**

```python
# tests/test_migrations_0007.py
def test_alert_tables(conn):
    names = {r["table_name"] for r in conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='regulation'").fetchall()}
    assert {"change_impact", "owner_assignment", "notification", "email_delivery"} <= names
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_migrations_0007.py -q` → FAIL

- [ ] **Step 3: 구현**

```python
# src/reg/migrations/versions/0007_alerts.py
"""개정 영향·담당자·알림 (spec 5.3, 9)."""
from alembic import op

revision = "0007"
down_revision = "0006"


def upgrade() -> None:
    op.execute("""
CREATE TABLE regulation.change_impact (
  id bigserial PRIMARY KEY,
  cause_work_id text NOT NULL,
  cause_version_id text NOT NULL,
  cause_from_version_id text,
  cause_path text NOT NULL,
  cause_change text NOT NULL CHECK (cause_change IN ('ADDED', 'MODIFIED', 'DELETED', 'RENUMBERED')),
  affected_work_id text NOT NULL,
  affected_version_id text,
  affected_path text NOT NULL,
  rel_type text NOT NULL,
  evidence text,
  impact_kind text NOT NULL,
  severity text NOT NULL CHECK (severity IN ('HIGH', 'MEDIUM', 'LOW')),
  hops int NOT NULL DEFAULT 1,
  status text NOT NULL DEFAULT 'NEW' CHECK (status IN ('NEW', 'ACKED', 'ACTION_REQUIRED', 'NO_ACTION', 'RESOLVED')),
  resolution_note text,
  resolved_by_version_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (cause_version_id, cause_path, affected_work_id, affected_path)
);
CREATE TABLE regulation.owner_assignment (
  id bigserial PRIMARY KEY,
  work_id text NOT NULL,
  email text NOT NULL,
  name text,
  org_unit text,
  role text NOT NULL DEFAULT 'OWNER' CHECK (role IN ('OWNER', 'DEPUTY')),
  UNIQUE (work_id, email)
);
CREATE TABLE regulation.notification (
  id bigserial PRIMARY KEY,
  impact_id bigint NOT NULL REFERENCES regulation.change_impact(id) ON DELETE CASCADE,
  recipient text NOT NULL,
  channel text NOT NULL DEFAULT 'email',
  severity text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  read_at timestamptz,
  sent_at timestamptz,
  UNIQUE (impact_id, recipient)
);
CREATE TABLE regulation.email_delivery (
  id bigserial PRIMARY KEY,
  recipient text NOT NULL,
  subject text NOT NULL,
  body text NOT NULL,
  notification_ids bigint[] NOT NULL,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'sent', 'failed')),
  attempts int NOT NULL DEFAULT 0,
  last_error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  sent_at timestamptz
);""")


def downgrade() -> None:
    op.execute("DROP TABLE regulation.email_delivery; DROP TABLE regulation.notification;"
               " DROP TABLE regulation.owner_assignment; DROP TABLE regulation.change_impact;")
```

`config/admins.yaml`에는 기관별 관리자를 적는다. 개발 환경 기본값은 Mailpit으로 받을 수 있는 가상 주소다.

```yaml
# 담당자가 지정되지 않은 규정의 알림을 받는 기관 관리자 (spec 9.2-5). 운영 전 실제 주소로 교체.
NST: [reg-admin-nst@nst-regulation.local]
KASI: [reg-admin-kasi@nst-regulation.local]
KIST: [reg-admin-kist@nst-regulation.local]
ETRI: [reg-admin-etri@nst-regulation.local]
```

compose와 settings는 Interfaces에 적은 값을 그대로 쓴다. conftest의 `neo4j_driver`는 아래와 같다.

```python
@pytest.fixture(scope="session")
def neo4j_driver():
    import time

    from neo4j import GraphDatabase
    from testcontainers.core.container import DockerContainer

    c = DockerContainer("neo4j:5.26-community").with_exposed_ports(7687).with_env("NEO4J_AUTH", "neo4j/testpass1234")
    with c:
        uri = f"bolt://{c.get_container_host_ip()}:{c.get_exposed_port(7687)}"
        drv = GraphDatabase.driver(uri, auth=("neo4j", "testpass1234"))
        for _ in range(90):
            try:
                drv.verify_connectivity()
                break
            except Exception:
                time.sleep(1)
        yield drv
        drv.close()
```

- [ ] **Step 4: 통과 확인 후 커밋** — `uv run pytest tests/test_migrations_0007.py -q` → PASS

```bash
git add infra/docker-compose.yml config/admins.yaml src/reg/settings.py .env.example pyproject.toml uv.lock \
        src/reg/migrations/versions/0007_alerts.py tests/conftest.py tests/test_migrations_0007.py
git commit -m "feat(alerts): Neo4j and SMTP infrastructure, impact/owner/notification tables"
```

---

### Task 2: 그래프 투영 (`reg graph sync`)

**Files:**
- Create: `src/reg/graph/__init__.py`, `src/reg/graph/sync.py`, `tests/test_graph.py`
- Modify: `src/reg/cli.py` (`reg graph sync`)

**Interfaces:**
- `sync_graph(conn, driver) -> dict`
  - `Reg*` 노드를 모두 지운다(배치 1만 건).
  - 노드
    - `(:RegInstitution {code, name})`
    - `(:RegWork {work_id, title, kind, institution, version_id})`: 현행 버전 기준
    - `(:RegProvision {key: work_id+'|'+path, work_id, path, label, heading})`: 현행 버전의 조·항·호·부칙·별표
  - 관계
    - `(:RegInstitution)-[:ISSUES]->(:RegWork)`
    - `(:RegWork)-[:HAS_PROVISION]->(:RegProvision)`
    - 참조
      - 현행 버전 조항의 `reference` 중 RESOLVED이고 `target_work_id`가 있는 것을 쓴다.
      - 대상이 PROVISION이면 `(src:RegProvision)-[:REL]->(dst:RegProvision)`이고, 대상 조항이 없으면 그 조(article) 노드를 쓴다.
      - 대상이 WORK이면 `(src)-[:REL]->(:RegWork)`
      - `REL` 자리에는 rel_type이 그대로 들어간다(BASIS 등).
      - 속성: `evidence`, `source_path`, `resolution`, `review_status`
  - 반환값: `{"works", "provisions", "relations"}`
  - `UNWIND` 배치는 2,000건이다.

- [ ] **Step 1: 실패하는 테스트**

```python
# tests/test_graph.py
from reg.graph.sync import sync_graph


def test_sync_projects_current_provisions_and_relations(loaded, neo4j_driver):
    st = sync_graph(loaded, neo4j_driver)
    assert st["works"] == 1 and st["provisions"] > 50 and st["relations"] > 5
    with neo4j_driver.session() as s:
        r = s.run("MATCH (a:RegProvision {path:'a27.p3'})-[r:EXCEPTION]->(b:RegProvision) RETURN b.path AS p").single()
        assert r["p"] == "a27.p1"
        n = s.run("MATCH (:RegWork)-[:HAS_PROVISION]->(p) RETURN count(p) AS n").single()["n"]
    assert n == st["provisions"]
    assert sync_graph(loaded, neo4j_driver) == st  # 다시 해도 같다
```

- [ ] **Step 2: 실패 확인** — FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: 구현**

```python
# src/reg/graph/__init__.py
```

```python
# src/reg/graph/sync.py
"""PostgreSQL(기준) → Neo4j(파생) 전체 재투영. 현행 버전만, Reg* 라벨만 다룬다 (spec 5.5, D-05)."""
RELS = ("BASIS", "DELEGATION", "IMPLEMENTS", "MUTATIS", "EXCEPTION", "CITATION")
UNITS = ("article", "paragraph", "item", "subitem", "supplement", "supp_article", "annex")
BATCH = 2000


def _chunks(rows: list, n: int = BATCH):
    for i in range(0, len(rows), n):
        yield rows[i:i + n]


def sync_graph(conn, driver) -> dict:
    works = conn.execute(
        "SELECT w.id AS work_id, w.title, w.kind, i.code AS institution, i.name AS inst_name, v.id AS version_id"
        " FROM regulation.work w JOIN regulation.work_version v ON v.work_id = w.id AND v.version_state = 'CURRENT'"
        " LEFT JOIN regulation.institution i ON i.id = w.institution_id").fetchall()
    provs = conn.execute(
        "SELECT v.work_id, pv.path, pv.number_label AS label, pv.heading FROM regulation.work_version v"
        " JOIN regulation.version_provision vp ON vp.work_version_id = v.id"
        " JOIN regulation.provision_version pv ON pv.id = vp.provision_version_id"
        " WHERE v.version_state = 'CURRENT' AND pv.unit = ANY(%s)", (list(UNITS),)).fetchall()
    rels = conn.execute(
        "SELECT r.work_id, spv.path AS source_path, r.rel_type, r.target_kind, r.target_work_id, r.target_path,"
        " r.evidence_text AS evidence, r.resolution, r.review_status FROM regulation.reference r"
        " JOIN regulation.provision_version spv ON spv.id = r.source_pv_id"
        " JOIN regulation.version_provision vp ON vp.provision_version_id = spv.id"
        " JOIN regulation.work_version v ON v.id = vp.work_version_id AND v.version_state = 'CURRENT'"
        " WHERE r.resolution = 'RESOLVED' AND r.target_work_id IS NOT NULL"
        " AND r.target_kind IN ('PROVISION', 'WORK')").fetchall()
    keys = {f"{p['work_id']}|{p['path']}" for p in provs}
    current = {w["work_id"] for w in works}
    n_rel = 0
    with driver.session() as s:
        while s.run("MATCH (n) WHERE any(l IN labels(n) WHERE l STARTS WITH 'Reg') WITH n LIMIT 10000"
                    " DETACH DELETE n RETURN count(n) AS c").single()["c"]:
            pass
        s.run("CREATE CONSTRAINT reg_prov_key IF NOT EXISTS FOR (p:RegProvision) REQUIRE p.key IS UNIQUE")
        s.run("CREATE CONSTRAINT reg_work_id IF NOT EXISTS FOR (w:RegWork) REQUIRE w.work_id IS UNIQUE")
        for part in _chunks([dict(w) for w in works]):
            s.run("UNWIND $rows AS r MERGE (w:RegWork {work_id: r.work_id})"
                  " SET w.title = r.title, w.kind = r.kind, w.institution = r.institution, w.version_id = r.version_id"
                  " FOREACH (_ IN CASE WHEN r.institution IS NULL THEN [] ELSE [1] END |"
                  "   MERGE (i:RegInstitution {code: r.institution}) SET i.name = r.inst_name MERGE (i)-[:ISSUES]->(w))",
                  rows=part)
        for part in _chunks([{**dict(p), "key": f"{p['work_id']}|{p['path']}"} for p in provs]):
            s.run("UNWIND $rows AS r MATCH (w:RegWork {work_id: r.work_id})"
                  " MERGE (p:RegProvision {key: r.key}) SET p.work_id = r.work_id, p.path = r.path, p.label = r.label,"
                  " p.heading = r.heading MERGE (w)-[:HAS_PROVISION]->(p)", rows=part)
        by_type: dict[tuple[str, str], list[dict]] = {}
        for r in rels:
            if r["rel_type"] not in RELS or r["target_work_id"] not in current:
                continue
            src = f"{r['work_id']}|{r['source_path']}"
            if src not in keys:
                continue
            if r["target_kind"] == "WORK" or not r["target_path"]:
                kind, dst = "work", r["target_work_id"]
            else:
                tk = f"{r['target_work_id']}|{r['target_path']}"
                if tk not in keys:
                    tk = f"{r['target_work_id']}|{r['target_path'].split('.')[0]}"
                if tk not in keys:
                    continue
                kind, dst = "prov", tk
            by_type.setdefault((r["rel_type"], kind), []).append(
                {"src": src, "dst": dst, "evidence": r["evidence"], "source_path": r["source_path"],
                 "resolution": r["resolution"], "review_status": r["review_status"]})
        for (rel, kind), rows in by_type.items():
            target = "MATCH (b:RegWork {work_id: r.dst})" if kind == "work" else "MATCH (b:RegProvision {key: r.dst})"
            for part in _chunks(rows):
                s.run(f"UNWIND $rows AS r MATCH (a:RegProvision {{key: r.src}}) {target}"
                      f" MERGE (a)-[x:{rel} {{source_path: r.source_path, evidence: r.evidence}}]->(b)"
                      " SET x.resolution = r.resolution, x.review_status = r.review_status", rows=part)
                n_rel += len(part)
    return {"works": len(works), "provisions": len(provs), "relations": n_rel}
```

`cli.py`에 `graph = typer.Typer(...)`와 `@graph.command("sync")`를 추가한다. 이 명령은 `neo4j.GraphDatabase.driver(s.neo4j_url, auth=(s.neo4j_user, s.neo4j_password))`로 `sync_graph`를 실행하고 결과를 출력한다.

- [ ] **Step 4: 통과 확인 후 커밋** — `uv run pytest tests/test_graph.py -q` → PASS

```bash
git add src/reg/graph src/reg/cli.py tests/test_graph.py
git commit -m "feat(graph): project current provisions and references into Neo4j"
```

---

### Task 3: 영향 분석

**Files:**
- Create: `src/reg/alerts/__init__.py`, `src/reg/alerts/impact.py`, `tests/test_impact.py`

**Interfaces:**
- `severity(change: str, rel: str) -> str`: Global Constraints 표를 따른다.
- `analyze_version(conn, driver, work_id: str, version_id: str) -> list[dict]`
  1. `provision_change`에서 `to_version_id = version_id`이고 `ANNOTATION_ONLY`가 아닌 변경을 모은다. 각 변경의 원인 경로는 `to` 경로이고, DELETED면 `from` 경로다.
  2. 원인 키 집합을 만든다. `work_id|경로`와, 그 경로의 조(article) 키를 함께 넣는다. ADDED는 WORK 단위 원인으로 본다.
  3. Cypher로 이 키들을 가리키는 `(src:RegProvision)-[r]->(t)`를 찾는다.
     - `src.work_id <> work_id`(같은 문서 안의 참조는 뺀다)
     - 1단계는 직접 참조다.
     - 2단계: 1단계의 `src` 규정 전체(RegWork)나 그 조를 `DELEGATION|IMPLEMENTS`로 가리키는 다른 규정의 조항
  4. 결과마다 `change_impact`를 `ON CONFLICT DO NOTHING`으로 넣는다.
  5. 새로 들어간 행 목록을 돌려준다.
- `impact_kind`: "참조 대상 삭제" | "근거·위임·준용 대상 개정" | "참조 대상 개정" | "참조 번호 이동" | "관련 법령 조문 신설"

- [ ] **Step 1: 실패하는 테스트**

```python
# tests/test_impact.py
from datetime import date

from reg.alerts.impact import analyze_version, severity
from reg.collect.archive import store
from reg.collect.sniff import FileKind
from reg.graph.sync import sync_graph
from reg.load.loader import add_version, rebuild_work, upsert_work
from reg.refs import resolve_and_store
from reg.storage.blob import LocalBlobStore
from reg.structure.effective import Effective
from reg.structure.model import ParsedDoc, Prov

T = date(2026, 10, 2)


def _ver(conn, blob, wid, title, provs, d, tag):
    sid = store(conn, blob, source="alio", url="u", content=b"%PDF" + tag, kind=FileKind("application/pdf", "pdf"),
                meta={}).id
    return add_version(conn, wid, sid, ParsedDoc(title, None, [], provs), Effective(d, "api", "CONFIRMED", d))


def setup(conn, tmp_path, law_v2):
    blob = LocalBlobStore(tmp_path)
    upsert_work(conn, "kr/law/L1", "법률", "가상 연구법", None, {})
    _ver(conn, blob, "kr/law/L1", "가상 연구법", [Prov("a5", "article", "제5조", "정산", "정산은 7일 이내에 한다."),
                                              Prov("a6", "article", "제6조", "기록", "기록한다.")], date(2020, 1, 1), b"L1")
    inst = conn.execute("INSERT INTO regulation.institution (code, name, kind) VALUES ('KASI','천문연','GRI')"
                        " RETURNING id").fetchone()["id"]
    upsert_work(conn, "kr/reg/KASI/여비", "INTERNAL_REG", "여비규정", inst, {})
    _ver(conn, blob, "kr/reg/KASI/여비", "여비규정",
         [Prov("a3", "article", "제3조", "정산", "「가상 연구법」 제5조에 따라 정산한다."),
          Prov("a4", "article", "제4조", "기록", "「가상 연구법」 제6조를 참고한다."),
          Prov("a7", "article", "제7조", "기타", "제3조에도 불구하고 따로 정한다.")], date(2021, 1, 1), b"R1")
    rebuild_work(conn, "kr/reg/KASI/여비", T)
    vid = _ver(conn, blob, "kr/law/L1", "가상 연구법", law_v2, date(2026, 1, 1), b"L2")
    rebuild_work(conn, "kr/law/L1", T)
    for w in ("kr/law/L1", "kr/reg/KASI/여비"):
        resolve_and_store(conn, w)
    conn.commit()
    return vid


def test_severity_table():
    assert severity("DELETED", "CITATION") == "HIGH" and severity("MODIFIED", "BASIS") == "HIGH"
    assert severity("MODIFIED", "CITATION") == "MEDIUM" and severity("RENUMBERED", "BASIS") == "MEDIUM"
    assert severity("ADDED", "CITATION") == "LOW"


def test_modified_basis_creates_high_impact_once(conn, tmp_path, neo4j_driver):
    vid = setup(conn, tmp_path, [Prov("a5", "article", "제5조", "정산", "정산은 10일 이내에 한다."),
                                 Prov("a6", "article", "제6조", "기록", "기록한다.")])
    sync_graph(conn, neo4j_driver)
    rows = analyze_version(conn, neo4j_driver, "kr/law/L1", vid)
    got = [(r["affected_work_id"], r["affected_path"], r["cause_path"], r["severity"], r["rel_type"]) for r in rows]
    assert got == [("kr/reg/KASI/여비", "a3", "a5", "HIGH", "BASIS")]   # a4(제6조 참조)는 변경 없음 → 영향 없음
    assert analyze_version(conn, neo4j_driver, "kr/law/L1", vid) == []  # 재스캔해도 중복 없음
    assert conn.execute("SELECT count(*) AS n FROM regulation.change_impact").fetchone()["n"] == 1


def test_annotation_only_change_has_no_impact(conn, tmp_path, neo4j_driver):
    v2 = [Prov("a5", "article", "제5조", "정산", "정산은 7일 이내에 한다.", annotations=["<개정 2026.1.1.>"]),
          Prov("a6", "article", "제6조", "기록", "기록한다.")]
    vid = setup(conn, tmp_path, v2)
    sync_graph(conn, neo4j_driver)
    assert analyze_version(conn, neo4j_driver, "kr/law/L1", vid) == []


def test_deleted_target_is_high(conn, tmp_path, neo4j_driver):
    vid = setup(conn, tmp_path, [Prov("a5", "article", "제5조", "정산", "정산은 7일 이내에 한다.")])
    sync_graph(conn, neo4j_driver)
    rows = analyze_version(conn, neo4j_driver, "kr/law/L1", vid)
    assert [(r["affected_path"], r["cause_change"], r["severity"]) for r in rows] == [("a4", "DELETED", "HIGH")]
```

- [ ] **Step 2: 실패 확인** — FAIL

- [ ] **Step 3: 구현**

```python
# src/reg/alerts/__init__.py
```

```python
# src/reg/alerts/impact.py
"""개정 영향 분석 (spec 9.2): 실질 변경 조항 → Neo4j 역방향 탐색 → change_impact."""
STRONG = {"BASIS", "DELEGATION", "MUTATIS", "IMPLEMENTS"}
KIND = {("DELETED", None): "참조 대상 삭제", ("MODIFIED", "strong"): "근거·위임·준용 대상 개정",
        ("MODIFIED", "weak"): "참조 대상 개정", ("RENUMBERED", None): "참조 번호 이동",
        ("ADDED", None): "관련 법령 조문 신설"}


def severity(change: str, rel: str) -> str:
    if change == "DELETED" or (change == "MODIFIED" and rel in STRONG):
        return "HIGH"
    if change in ("MODIFIED", "RENUMBERED"):
        return "MEDIUM"
    return "LOW"


def _kind(change: str, rel: str) -> str:
    if change == "MODIFIED":
        return KIND[(change, "strong" if rel in STRONG else "weak")]
    return KIND[(change, None)]


def _changes(conn, version_id: str) -> list[dict]:
    return conn.execute(
        "SELECT c.kind, c.from_version_id, coalesce(t.path, f.path) AS path, f.path AS from_path"
        " FROM regulation.provision_change c"
        " LEFT JOIN regulation.provision_version t ON t.id = c.to_pv_id"
        " LEFT JOIN regulation.provision_version f ON f.id = c.from_pv_id"
        " WHERE c.to_version_id = %s AND c.kind <> 'ANNOTATION_ONLY'", (version_id,)).fetchall()


Q1 = ("UNWIND $causes AS c MATCH (src:RegProvision)-[r]->(t) WHERE (t:RegProvision AND t.key = c.key)"
      " OR (t:RegWork AND t.work_id = c.work AND c.kind = 'ADDED')"
      " WITH c, src, r WHERE src.work_id <> c.work"
      " RETURN c.path AS cause_path, c.kind AS change, src.work_id AS work_id, src.path AS path, type(r) AS rel,"
      " r.evidence AS evidence, 1 AS hops")
Q2 = ("UNWIND $first AS f MATCH (src:RegProvision)-[r:DELEGATION|IMPLEMENTS]->(t)"
      " WHERE (t:RegWork AND t.work_id = f.work_id) OR (t:RegProvision AND t.work_id = f.work_id"
      " AND split(t.path, '.')[0] = split(f.path, '.')[0])"
      " WITH f, src, r WHERE src.work_id <> f.work_id AND src.work_id <> f.cause_work"
      " RETURN f.cause_path AS cause_path, f.change AS change, src.work_id AS work_id, src.path AS path,"
      " type(r) AS rel, r.evidence AS evidence, 2 AS hops")


def analyze_version(conn, driver, work_id: str, version_id: str) -> list[dict]:
    changes = _changes(conn, version_id)
    if not changes:
        return []
    causes = []
    for ch in changes:
        path = ch["from_path"] if ch["kind"] == "DELETED" else ch["path"]
        for key_path in dict.fromkeys([path, path.split(".")[0]]):
            causes.append({"key": f"{work_id}|{key_path}", "work": work_id, "path": path, "kind": ch["kind"]})
    from_version = changes[0]["from_version_id"]
    with driver.session() as s:
        first = [dict(r) for r in s.run(Q1, causes=causes)]
        second = [dict(r) for r in s.run(Q2, first=[{**f, "cause_work": work_id} for f in first])] if first else []
    out = []
    for f in first + second:
        sev = severity(f["change"], f["rel"])
        cur = conn.execute("SELECT id FROM regulation.work_version WHERE work_id = %s AND version_state = 'CURRENT'",
                           (f["work_id"],)).fetchone()
        row = conn.execute(
            "INSERT INTO regulation.change_impact (cause_work_id, cause_version_id, cause_from_version_id, cause_path,"
            " cause_change, affected_work_id, affected_version_id, affected_path, rel_type, evidence, impact_kind,"
            " severity, hops) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING *",
            (work_id, version_id, from_version, f["cause_path"], f["change"], f["work_id"], cur["id"] if cur else None,
             f["path"], f["rel"], f["evidence"], _kind(f["change"], f["rel"]), sev, f["hops"])).fetchone()
        if row:
            out.append(row)
    conn.commit()
    return sorted(out, key=lambda r: (r["affected_work_id"], r["affected_path"]))
```

- [ ] **Step 4: 통과 확인 후 커밋** — `uv run pytest tests/test_impact.py -q` → 4 PASS

```bash
git add src/reg/alerts tests/test_impact.py
git commit -m "feat(alerts): change impact analysis over the Neo4j reference graph"
```

---

### Task 4: 개정 이벤트와 스캔

**Files:**
- Modify: `src/reg/process.py`
- Create: `src/reg/alerts/scan.py`, `tests/test_scan.py`
- Modify: `src/reg/cli.py` (`reg alerts scan`)

**Interfaces:**
- process 묶음 처리
  - 묶음을 처리하기 전, 그 규범문서에 이미 있던 버전 id 집합과 그중 가장 늦은 시행일을 기억해 둔다.
  - `rebuild_work` 뒤에 새로 추가된 버전 중 시행일이 기존 최대 시행일보다 늦은 것이 있으면, 그 버전마다 outbox `regulation.version_loaded` `{"work_id", "version_id"}`를 기록한다.
  - 기존 버전이 없던 규범문서(첫 적재)는 기록하지 않는다.
- `scan_once(conn, driver, limit=100) -> dict`
  - `regulation.version_loaded` 이벤트를 하나씩 가져온다(SKIP LOCKED).
  - 이벤트마다 `analyze_version`을 실행하고, 성공하면 processed로 표시한다.
  - 실패하면 attempts를 1 늘리고 last_error를 남긴다. 이 경우 처리 완료로 표시하지 않는다.
  - 반환값: `{"claimed", "ok", "failed", "impacts"}`
- CLI `reg alerts scan`: 그래프를 sync한 뒤 `scan_once`를 반복한다.

- [ ] **Step 1: 실패하는 테스트**

```python
# tests/test_scan.py
import json
from datetime import date

from reg.alerts.scan import scan_once
from reg.process import process_once
from reg.storage.blob import LocalBlobStore
from tests.test_impact import setup
from tests.test_process import FX, seed_alio


def test_first_load_emits_no_version_loaded(conn, tmp_path):
    blob = LocalBlobStore(tmp_path)
    seed_alio(conn, blob, (FX / "samples" / "kasi-yeobi-339.pdf").read_bytes())
    process_once(conn, blob, today=date(2026, 10, 2))
    n = conn.execute("SELECT count(*) AS n FROM regulation.outbox WHERE topic='regulation.version_loaded'").fetchone()
    assert n["n"] == 0


def test_newer_version_emits_event(conn, tmp_path):
    blob = LocalBlobStore(tmp_path)
    data = (FX / "samples" / "kasi-yeobi-339.pdf").read_bytes()
    seed_alio(conn, blob, data)
    process_once(conn, blob, today=date(2026, 10, 2))
    seed_alio(conn, blob, data.replace(b"2024", b"2025", 1) + b" ", file_name="여비규정(2025년도 개정).pdf", ord_=1)
    process_once(conn, blob, today=date(2026, 10, 2))
    ev = conn.execute("SELECT payload FROM regulation.outbox WHERE topic='regulation.version_loaded'").fetchall()
    assert len(ev) <= 1  # 시행일이 같으면 새 버전이 '더 최신'이 아닐 수 있다 — 아래 단위 테스트가 규칙을 고정


class DownDriver:
    def session(self):
        raise RuntimeError("neo4j down")


def test_scan_marks_processed_or_retries(conn, tmp_path, neo4j_driver):
    from reg.graph.sync import sync_graph
    from tests.test_impact import Prov

    vid = setup(conn, tmp_path, [Prov("a5", "article", "제5조", "정산", "정산은 10일 이내에 한다."),
                                 Prov("a6", "article", "제6조", "기록", "기록한다.")])
    conn.execute("INSERT INTO regulation.outbox (topic, payload) VALUES ('regulation.version_loaded', %s)",
                 (json.dumps({"work_id": "kr/law/L1", "version_id": vid}),))
    conn.commit()
    st = scan_once(conn, DownDriver())
    assert st == {"claimed": 1, "ok": 0, "failed": 1, "impacts": 0}
    sync_graph(conn, neo4j_driver)
    st = scan_once(conn, neo4j_driver)
    assert st["ok"] == 1 and st["impacts"] == 1
    assert scan_once(conn, neo4j_driver)["claimed"] == 0
```

- [ ] **Step 2: 실패 확인** — FAIL

- [ ] **Step 3: 구현**

`process.py`의 `process_once` 묶음 처리를 다음과 같이 바꾼다.
- **핸들러 호출 전**: 묶음의 work를 미리 알 수 없으므로, 핸들러 결과로 얻은 work마다 처음 볼 때 기존 상태를 조회한다.
  - 조회 쿼리: `SELECT id, effective_from FROM regulation.work_version WHERE work_id=%s`
  - 이 조회는 `add_version`이 실행되기 전 상태여야 한다. 그래서 핸들러가 `(wid, vid, doc, eff)`를 돌려줄 때 버전이 이미 추가되어 있다는 점을 고려해, **이번 묶음에서 추가된 vid들을 제외한** 기존 버전 집합을 쓴다.
- **`rebuild_work` 뒤**
  - 기존 버전 집합이 비어 있지 않으면, 이번 묶음의 vid 중 시행일이 기존 최대 시행일보다 늦은 것마다 `outbox.write(conn, "regulation.version_loaded", {"work_id": wid, "version_id": vid})`를 호출한다.

```python
# src/reg/alerts/scan.py
"""개정 이벤트 소비 → 영향 분석 (Q&A와 독립된 경로, spec 9)."""
from reg.alerts.impact import analyze_version

TOPIC = "regulation.version_loaded"
MAX_ATTEMPTS = 3


def scan_once(conn, driver, limit: int = 100) -> dict:
    st = {"claimed": 0, "ok": 0, "failed": 0, "impacts": 0}
    for _ in range(limit):
        ev = conn.execute("SELECT id, payload, attempts FROM regulation.outbox WHERE topic = %s AND processed_at IS NULL"
                          " AND attempts < %s ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED", (TOPIC, MAX_ATTEMPTS)).fetchone()
        if ev is None:
            break
        st["claimed"] += 1
        try:
            rows = analyze_version(conn, driver, ev["payload"]["work_id"], ev["payload"]["version_id"])
            conn.execute("UPDATE regulation.outbox SET processed_at = now(), last_error = NULL WHERE id = %s", (ev["id"],))
            st["ok"] += 1
            st["impacts"] += len(rows)
        except Exception as e:
            conn.rollback()
            conn.execute("UPDATE regulation.outbox SET attempts = attempts + 1, last_error = %s WHERE id = %s",
                         (f"{type(e).__name__}: {e}"[:2000], ev["id"]))
            st["failed"] += 1
        conn.commit()
    return st
```

- [ ] **Step 4: 통과 확인 후 커밋** — `uv run pytest -q` → 전체 PASS

```bash
git add src/reg/process.py src/reg/alerts/scan.py src/reg/cli.py tests/test_scan.py
git commit -m "feat(alerts): version_loaded events and impact scanning independent of Q&A"
```

---

### Task 5: 담당자·알림·메일

**Files:**
- Create: `src/reg/alerts/notify.py`, `tests/test_notify.py`
- Modify: `src/reg/cli.py` (`reg owners import <csv>`, `reg alerts notify`)

**Interfaces:**
- `import_owners(conn, rows: list[dict]) -> int`
  - CSV 열: `work_id`, `email`, `name`, `org_unit`, `role`
  - upsert한다.
- `build_notifications(conn, admins: dict[str, list[str]]) -> int`
  - `status='NEW'`인 impact마다 수신자를 정한다.
    - `owner_assignment(affected_work_id)`의 담당자
    - 없으면 `admins[기관코드]`
  - `notification`을 `ON CONFLICT DO NOTHING`으로 넣는다.
- `send_due(conn, mailer, now: datetime, digest_hour: int = 8) -> dict`
  - 대상: `sent_at IS NULL`인 알림
  - 발송 시점
    - HIGH는 즉시 보낸다.
    - 그 밖에는 `now.hour >= digest_hour`이고 당일 이미 보낸 묶음이 없을 때 보낸다.
  - 수신자별로 묶어 메일 하나를 만든다.
    - 제목: `[규정 개정 알림] 영향 {n}건 (높음 {h})`
    - 본문: 원인 규범문서, 조, 변경 종류 → 영향 규정, 조, 관계, 심각도, 근거 문구. 그리고 알림함 링크 `http://<웹>/alerts?id=`
  - `email_delivery`에 기록하고, 성공하면 `sent`와 각 notification의 `sent_at`을 기록한다.
  - 실패하면 `attempts`를 1 늘린다.
  - 반환값: `{"emails", "notifications", "failed"}`
- `class SmtpMailer(host, port, sender)`: `.send(to, subject, body)` — `smtplib.SMTP`, UTF-8 본문

- [ ] **Step 1: 실패하는 테스트**

```python
# tests/test_notify.py
from datetime import datetime

from reg.alerts.notify import build_notifications, import_owners, send_due


class FakeMailer:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def send(self, to, subject, body):
        if self.fail:
            raise OSError("smtp down")
        self.sent.append((to, subject, body))


def impact(conn, work="kr/reg/KASI/여비", path="a3", sev="HIGH", cause_path="a5"):
    conn.execute("INSERT INTO regulation.institution (code, name, kind) VALUES ('KASI','천문연','GRI') ON CONFLICT DO NOTHING")
    return conn.execute(
        "INSERT INTO regulation.change_impact (cause_work_id, cause_version_id, cause_path, cause_change, affected_work_id,"
        " affected_path, rel_type, evidence, impact_kind, severity) VALUES ('kr/law/L1','kr/law/L1@2026-01-01',%s,"
        "'MODIFIED',%s,%s,'BASIS','「가상 연구법」 제5조에 따라','근거·위임·준용 대상 개정',%s) RETURNING id",
        (cause_path, work, path, sev)).fetchone()["id"]


def test_owner_then_admin_fallback_and_idempotent(conn):
    impact(conn)
    impact(conn, work="kr/reg/KASI/복무", path="a9", sev="MEDIUM")
    import_owners(conn, [{"work_id": "kr/reg/KASI/여비", "email": "owner@x", "name": "담당", "org_unit": "회계", "role": "OWNER"}])
    assert build_notifications(conn, {"KASI": ["admin@x"]}) == 2
    assert build_notifications(conn, {"KASI": ["admin@x"]}) == 0
    rec = sorted(r["recipient"] for r in conn.execute("SELECT recipient FROM regulation.notification").fetchall())
    assert rec == ["admin@x", "owner@x"]


def test_high_sent_immediately_others_in_digest(conn):
    impact(conn)
    impact(conn, path="a4", sev="MEDIUM", cause_path="a6")
    import_owners(conn, [{"work_id": "kr/reg/KASI/여비", "email": "owner@x", "name": "", "org_unit": "", "role": "OWNER"}])
    build_notifications(conn, {})
    m = FakeMailer()
    st = send_due(conn, m, datetime(2026, 10, 2, 6, 0))
    assert st["emails"] == 1 and st["notifications"] == 1 and "높음 1" in m.sent[0][1]
    st = send_due(conn, m, datetime(2026, 10, 2, 9, 0))
    assert st["notifications"] == 1 and len(m.sent) == 2


def test_failure_is_recorded(conn):
    impact(conn)
    import_owners(conn, [{"work_id": "kr/reg/KASI/여비", "email": "o@x", "name": "", "org_unit": "", "role": "OWNER"}])
    build_notifications(conn, {})
    st = send_due(conn, FakeMailer(fail=True), datetime(2026, 10, 2, 9, 0))
    assert st["failed"] == 1
    d = conn.execute("SELECT status, attempts FROM regulation.email_delivery").fetchone()
    assert (d["status"], d["attempts"]) == ("failed", 1)
    assert conn.execute("SELECT count(*) AS n FROM regulation.notification WHERE sent_at IS NULL").fetchone()["n"] == 1
```

- [ ] **Step 2: 실패 확인** — FAIL

- [ ] **Step 3: 구현**

```python
# src/reg/alerts/notify.py
"""담당자 알림 (spec 9.2-5): 담당자 → 기관 관리자, 높음 즉시·그 밖 하루 묶음, 메일 발송 기록."""
import smtplib
from collections import defaultdict
from datetime import datetime
from email.message import EmailMessage

WEB = "http://192.168.0.3:21060"


class SmtpMailer:
    def __init__(self, host: str, port: int, sender: str):
        self.host, self.port, self.sender = host, port, sender

    def send(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.sender, to, subject
        msg.set_content(body, charset="utf-8")
        with smtplib.SMTP(self.host, self.port, timeout=10) as s:
            s.send_message(msg)


def import_owners(conn, rows: list[dict]) -> int:
    for r in rows:
        conn.execute("INSERT INTO regulation.owner_assignment (work_id, email, name, org_unit, role)"
                     " VALUES (%(work_id)s, %(email)s, %(name)s, %(org_unit)s, %(role)s)"
                     " ON CONFLICT (work_id, email) DO UPDATE SET name = EXCLUDED.name, org_unit = EXCLUDED.org_unit,"
                     " role = EXCLUDED.role", {**r, "role": r.get("role") or "OWNER"})
    conn.commit()
    return len(rows)


def build_notifications(conn, admins: dict[str, list[str]]) -> int:
    n = 0
    for imp in conn.execute(
            "SELECT ci.id, ci.affected_work_id, ci.severity, i.code FROM regulation.change_impact ci"
            " LEFT JOIN regulation.work w ON w.id = ci.affected_work_id"
            " LEFT JOIN regulation.institution i ON i.id = w.institution_id WHERE ci.status = 'NEW'").fetchall():
        owners = [r["email"] for r in conn.execute("SELECT email FROM regulation.owner_assignment WHERE work_id = %s",
                                                   (imp["affected_work_id"],)).fetchall()]
        code = imp["code"] or imp["affected_work_id"].split("/")[2] if imp["affected_work_id"].startswith("kr/reg/") else imp["code"]
        for to in owners or admins.get(code or "", []):
            n += conn.execute("INSERT INTO regulation.notification (impact_id, recipient, severity) VALUES (%s,%s,%s)"
                              " ON CONFLICT DO NOTHING", (imp["id"], to, imp["severity"])).rowcount
    conn.commit()
    return n


def _body(rows: list[dict]) -> str:
    lines = ["규정 개정으로 검토가 필요한 조항이 있습니다.", ""]
    for r in rows:
        lines += [f"- [{ {'HIGH': '높음', 'MEDIUM': '중간', 'LOW': '낮음'}[r['severity']] }] {r['impact_kind']}",
                  f"  원인: {r['cause_work_id']} {r['cause_path']} ({r['cause_change']})",
                  f"  영향: {r['affected_work_id']} {r['affected_path']} — {r['rel_type']}",
                  f"  근거 문구: {r['evidence'] or '-'}", f"  알림함: {WEB}/alerts?id={r['impact_id']}", ""]
    lines.append("이 메일은 NST 규정·법령 플랫폼이 자동으로 보냈습니다. 법적 판단이 아니며 소관부서 검토가 필요합니다.")
    return "\n".join(lines)


def send_due(conn, mailer, now: datetime, digest_hour: int = 8) -> dict:
    st = {"emails": 0, "notifications": 0, "failed": 0}
    rows = conn.execute(
        "SELECT n.id, n.recipient, n.severity, n.impact_id, ci.cause_work_id, ci.cause_path, ci.cause_change,"
        " ci.affected_work_id, ci.affected_path, ci.rel_type, ci.evidence, ci.impact_kind"
        " FROM regulation.notification n JOIN regulation.change_impact ci ON ci.id = n.impact_id"
        " WHERE n.sent_at IS NULL ORDER BY n.id").fetchall()
    digest_open = now.hour >= digest_hour
    by_to: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["severity"] == "HIGH" or digest_open:
            by_to[r["recipient"]].append(r)
    for to, items in by_to.items():
        high = sum(1 for r in items if r["severity"] == "HIGH")
        subject = f"[규정 개정 알림] 영향 {len(items)}건 (높음 {high})"
        ids = [r["id"] for r in items]
        d = conn.execute("INSERT INTO regulation.email_delivery (recipient, subject, body, notification_ids)"
                         " VALUES (%s,%s,%s,%s) RETURNING id", (to, subject, _body(items), ids)).fetchone()["id"]
        try:
            mailer.send(to, subject, _body(items))
            conn.execute("UPDATE regulation.email_delivery SET status = 'sent', attempts = attempts + 1, sent_at = now()"
                         " WHERE id = %s", (d,))
            conn.execute("UPDATE regulation.notification SET sent_at = now() WHERE id = ANY(%s)", (ids,))
            st["emails"] += 1
            st["notifications"] += len(ids)
        except Exception as e:
            conn.execute("UPDATE regulation.email_delivery SET status = 'failed', attempts = attempts + 1,"
                         " last_error = %s WHERE id = %s", (f"{type(e).__name__}: {e}"[:500], d))
            st["failed"] += 1
        conn.commit()
    return st
```

`build_notifications`의 기관 코드 계산은 다음 한 줄로 쓴다. 위 블록의 조건식은 이 줄로 바꾼다.

```python
code = imp["code"] or (imp["affected_work_id"].split("/")[2] if imp["affected_work_id"].startswith("kr/reg/") else None)
```

CLI는 두 가지다.
- `reg owners import FILE.csv`: `csv.DictReader`로 읽어 `import_owners`를 호출한다.
- `reg alerts notify`: `config/admins.yaml`을 읽고 `build_notifications`를 실행한 뒤, `SmtpMailer(s.smtp_host, s.smtp_port, s.smtp_from)`로 `send_due(conn, mailer, datetime.now(ZoneInfo('Asia/Seoul')))`를 실행한다.

- [ ] **Step 4: 통과 확인 후 커밋** — `uv run pytest tests/test_notify.py -q` → 3 PASS

```bash
git add src/reg/alerts/notify.py src/reg/cli.py tests/test_notify.py
git commit -m "feat(alerts): owner assignment, notifications with immediate/digest email delivery"
```

---

### Task 6: 알림함 API·화면, 사후 검증, 실연결

**Files:**
- Create: `src/reg/alerts/backtest.py`, `tests/test_alerts_api.py`, `apps/web/src/app/alerts/page.tsx`
- Modify: `src/reg/api/app.py`, `apps/web/src/app/layout.tsx`(내비게이션 `개정 알림`), `apps/web/src/lib/api.ts`, `src/reg/cli.py` (`reg alerts backtest`)

**Interfaces:**
- API
  - `GET /api/v1/alerts?status=NEW|...&institution=&severity=`
    - 반환 필드: `id`, `severity`, `impact_kind`, `status`, `cause_*`, `affected_*`, `rel_type`, `evidence`, `created_at`, `cause_title`, `affected_title`
  - `GET /api/v1/alerts/{id}`
    - 위 필드에 다음을 더한다.
      - `cause_old`, `cause_new`: 원인 조항의 이전·이후 본문
      - `affected_text`: 영향 조항의 현행 본문
      - `recipients`
  - `POST /api/v1/alerts/{id}/status` 본문 `{status, note}`
    - status는 ACKED, ACTION_REQUIRED, NO_ACTION, RESOLVED 중 하나다.
    - NO_ACTION이면 note가 필수다. 없으면 422.
- 웹 `/alerts`: 시안 `docs/ui/Alerts.dc.html`을 따른다.
  - 왼쪽: 심각도별 목록(처리 필요 / 완료 탭)
  - 오른쪽: 영향 조문, 상위 조문 신구 비교, 처리 버튼(조치 필요·조치 불필요(사유)·확인)
- `backtest(conn, driver, limit=200) -> dict`
  - 버전이 2개 이상인 규범문서마다 최신 버전에 대해 `analyze_version`을 실행한다(재생).
  - 반환값: `{"works": n, "impacts": m, "by_severity": {...}}`
  - 재생으로 생긴 영향은 `status='RESOLVED'`, `resolution_note='backtest'`로 표시한다. 그래서 알림은 나가지 않는다.
  - 결과는 `docs/reports/2026-10-02-impact-backtest.md`에 기록한다.

- [ ] **Step 1: API 실패하는 테스트**

```python
# tests/test_alerts_api.py
from fastapi.testclient import TestClient

from reg.api.app import create_app
from reg.storage.blob import LocalBlobStore
from tests.test_notify import impact


def test_alerts_list_detail_and_status(conn, migrated, tmp_path):
    iid = impact(conn)
    conn.commit()
    with TestClient(create_app(migrated[0], LocalBlobStore(tmp_path))) as c:
        rows = c.get("/api/v1/alerts", params={"status": "NEW"}).json()
        assert [r["id"] for r in rows] == [iid] and rows[0]["severity"] == "HIGH"
        d = c.get(f"/api/v1/alerts/{iid}").json()
        assert d["affected_path"] == "a3" and "recipients" in d
        assert c.post(f"/api/v1/alerts/{iid}/status", json={"status": "NO_ACTION"}).status_code == 422
        assert c.post(f"/api/v1/alerts/{iid}/status", json={"status": "NO_ACTION", "note": "영향 없음 확인"}).json()["ok"]
        assert c.get("/api/v1/alerts", params={"status": "NEW"}).json() == []
```

- [ ] **Step 2: 구현과 통과 확인**
  - API는 Interfaces를 따른다.
  - `cause_old`와 `cause_new`는 `provision_change`에서 원인 버전의 해당 경로 `from_pv` / `to_pv` 본문을 가져온다.
  - 웹 화면은 기존 컴포넌트 스타일(`card`, `chip`, `btn`)을 쓴다.

- [ ] **Step 3: 실연결**

```bash
docker compose -f infra/docker-compose.yml up -d neo4j mailpit-proxy
set -a; . ./.env; set +a
uv run reg db upgrade
uv run reg graph sync          # 현행 규범문서·조항·참조 투영
uv run reg alerts backtest     # 과거 개정 재생 → 보고서
uv run reg alerts scan         # 대기 중인 version_loaded 처리 (실데이터에 새 개정이 없으면 0)
bash scripts/run-dev.sh
```

Expected:
- `graph sync`가 출력하는 works 수가 현행 규범문서 수와 같다.
- backtest 보고서에는 실제 숫자만 적는다. 예: 내부규정 간 위임·참조로 생긴 영향 건수, 심각도 분포.
- `/alerts`에서 backtest 결과(RESOLVED 탭)를 볼 수 있다.

- [ ] **Step 4: 커밋**

```bash
git add src/reg/alerts/backtest.py src/reg/api/app.py src/reg/cli.py apps/web/src tests/test_alerts_api.py docs/reports
git commit -m "feat(alerts): alerts API and inbox, impact backtest report"
```

---

## Self-Review 결과

**스펙 대응**

| 스펙 | 반영 위치 |
|---|---|
| 9.1 출처 (법령·내부규정) | 처리기 공통 이벤트, Task 4 |
| 9.1 시행일 도래 사전 알림 | 이번 범위에서 제외하고 M5b에 일정 작업으로 둔다 |
| 9.2-1 실질 변경만 | Task 3 |
| 9.2-2 역방향 + 위임 2단계 | Task 3 |
| 9.2-3 심각도 | Task 3 |
| 9.2-4 검토 요약 (LLM) | 제외. 신구 비교만 보여준다. 검증 비용 대비 이득이 낮아 M6으로 넘긴다. |
| 9.2-5 담당자·관리자·즉시/묶음·멱등 | Task 5 |
| 9.2-6 상태 흐름 | Task 6. 새 버전 자동 연결과 기한 초과 재알림은 M5b로 넘긴다. |
| 12 사후 검증 | Task 6 |

**타입 일치**
- `change_impact` 컬럼명이 impact, notify, API, 테스트에서 같다.
- `analyze_version`이 돌려주는 행은 테이블 행 그대로다.
