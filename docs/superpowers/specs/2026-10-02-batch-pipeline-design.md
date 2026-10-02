# 일 배치 파이프라인 설계 (Airflow → 파싱 → RDB → OpenSearch·Neo4j)

- 작성: 2026-10-02 · 상태: **검토 요청**
- 상위 문서: `docs/PRD.md`, `docs/superpowers/specs/2026-10-01-regulation-platform-design.md`
- 범위: 데이터가 들어와 검색·질의응답·알림에 쓰이기까지의 배치 경로. 화면·API·질의응답 로직은 다루지 않는다.

---

## 0. 현재 상태와 이 문서가 채우는 것

단계별 코드는 대부분 있다. 다만 사람이 CLI 명령을 순서대로 손으로 실행하고 있다. 일정, 순서, 재시도, 실패 알림을 맡는 오케스트레이터(Airflow)가 없다.

| 단계 | 지금 있는 코드 | 지금 실행 방식 | 빈틈 (이 문서에서 설계) |
|---|---|---|---|
| ① 수집 | `reg collect alio`, `reg collect law` (`collect/alio_sync.py`, `law_sync.py`) | 수동 | 일정, 기관별 병렬·예의(요청 간격), 폐지 규정 감지, 실패 알림 |
| ①' 국내 법령 | `config/laws.yaml`에 적은 15개 법령만 받아 `regulation.work`에 섞어 저장 | 수동 | **현행 법령 전체(5,627건)를 별도 법령 DB에 일 배치로 미러링**하고, 내부규정과 외래키로 연계, 원문 URL·원문 조문 링크 (§3A) |
| ② 파싱 | `reg process --all` (`process.py`가 outbox를 소비해 추출→구조→시행일→적재) | 수동 | 배치 연결, 파서 버전 관리, 재파싱 정책, OCR 경로 |
| ③ RDB 적재 | 마이그레이션 0001~0007, `load/loader.py`, `refs.py`, `quality.py` | ②에 포함 | 목록 마스터의 상태(폐지), 조회용 뷰, 배치 실행 이력 연결 |
| ④ OpenSearch | `reg index build` (release 단위 전체 재색인) | 수동, 약 5분 + GPU | 변경분만 재임베딩(임베딩 캐시), 게시 품질 게이트, GPU 불가 시 처리 |
| ⑤ Neo4j | `reg graph sync` (전체 재투영), `reg alerts scan` | 수동 | 배치 연결, 잠금(구현됨) 활용 |
| ⑥ 알림 | `reg alerts notify` | 수동 | 매시간 실행, 하루 묶음 |
| ⑦ 기타 저장 | SeaweedFS(원본·보기 PDF), `request_log`, `fetch_run` | ①②에 포함 | 보관 기간, 로그 정리 |

원칙은 그대로 유지한다.
- **PostgreSQL이 기준(source of truth)이다.** OpenSearch와 Neo4j는 언제든 PostgreSQL에서 다시 만들 수 있는 파생 저장소다.
- **단계 사이는 outbox 이벤트로 잇는다.** Airflow는 순서와 일정만 맡는다. 어느 태스크를 다시 돌려도 결과가 같아야 한다(멱등).
- **배치 로직은 `reg` 패키지에만 둔다.** DAG는 얇게 유지한다. 그래야 CLI로도, Airflow로도 같은 코드가 돈다.

---

## 1. 전체 흐름

```
[02:00 KST] reg_alio_daily
  ├─ institutions_load        config/institutions.yaml → institution
  ├─ alio_collect[기관별]      목록→지문 비교→상세·파일 다운로드 → alio_rule, alio_rule_file, source_document, SeaweedFS
  │                            └ 새 파일마다 outbox: regulation.source_fetched
  ├─ alio_reconcile            목록에서 사라진 규정 → 폐지 후보 (§3.3)
  └─ (법령은 아래 별도 DAG)
        │ (Asset: regulation_raw 갱신)

[01:00 KST] reg_law_daily      (§3A, 별도 법령 DB `law` 스키마)
  ├─ law_changes               lawSearch.do target=lsHstInf&regDt=전날 → 바뀐 법령 목록(하루 약 100~200건)
  ├─ law_fetch[법령별]          lawService.do(MST) XML → 원본 보관 → law.law_version / law.article 적재
  ├─ law_current               현행 여부 갱신(새 MST가 현행, 이전 MST는 연혁), 폐지 법령 표시
  ├─ law_link                  내부규정 참조(reference)의 법령명·조문 → law.article 외래키 연결
  └─ law_promote               내부규정이 인용한 법령만 regulation.work로 승격(뷰어·검색·알림 대상)
                               └ 새 버전마다 outbox: regulation.law_fetched
        │ (Asset: law_mirror 갱신 → reg_process 트리거)
        ▼
reg_process  (Asset 트리거 + 03:30 안전망)
  ├─ process_events            outbox 소비: 추출(HWP/HWPX/PDF) → 구조 파싱 → 시행일 판정
  │                            → work / work_version / provision* / reference / review_task 적재
  │                            → 보기용 PDF 변환(HWP) → 새 개정이면 outbox: regulation.version_loaded
  └─ quality_report            파싱 실패·LOW_TEXT·번호 빈칸 집계 → 검수 큐, 실행 요약
        │ (Asset: regulation_structured 갱신)
        ▼
reg_publish
  ├─ graph_sync ─┐             PostgreSQL 현행 → Neo4j 재투영 (그래프 잠금 안)
  ├─ alerts_scan ┘             version_loaded 소비 → change_impact
  ├─ embed_check               GPU 임베딩 서버 상태 확인 (불가 시 색인만 미룸)
  ├─ index_build               변경분만 재임베딩 → 새 release 색인 (§6)
  ├─ index_gate                품질 게이트 통과 시 alias 전환 (게시)
  └─ eval_smoke                질의응답 회귀 평가 16문항 (게시 후 기록)

[매시 05분] reg_notify          change_impact → notification → 메일 (높음 즉시, 그 밖 08시 이후 하루 1회)
[일 04:00]  reg_maintenance     오래된 request_log·qa_log 정리, 이전 release 색인 삭제, 백업 확인
[수동]      reg_backfill        기관 추가·파서 변경 시 재처리 (conf로 기관·범위 지정)
```

---

## 1A. 모듈 구조 (출처별 분리)

### 1A.1 왜 나누나

외부 사이트는 서로 다르게, 예고 없이 바뀐다.
- ALIO는 JSON 필드명이나 파일 다운로드 방식이 바뀔 수 있다.
- law.go.kr는 DRF 파라미터, XML 구조, OC 키 정책이 바뀔 수 있다.

한 출처가 바뀌었을 때 **그 출처의 모듈만 열어 고치고, 그 모듈의 테스트만 다시 돌리면 되는 구조**가 목표다.

현재 구조의 문제:
- `collect/`에 ALIO(`alio.py`, `alio_sync.py`)와 law.go.kr(`lawgo.py`, `law_sync.py`)가 섞여 있다.
- `structure/law_xml.py`(법령 XML 파서)가 내부규정 파서 옆에 있다.
- `process.py`가 두 출처의 처리 함수를 직접 import한다(`HANDLERS` 딕셔너리).
- 마이그레이션이 하나의 이력이라 법령 테이블만 따로 바꾸기 어렵다.

### 1A.2 계층과 의존 방향

```
                 ┌──────────────── apps ────────────────┐
                 │  api · qa · cli · airflow/dags        │
                 └───────┬───────────────┬──────────────┘
                         │               │
      ┌──── sources ─────┴──┐   ┌── derived ──────────┐
      │ sources/alio        │   │ index (OpenSearch)  │
      │ sources/lawgo       │   │ graph (Neo4j)       │
      │ (sources/… 추가 가능) │   │ alerts              │
      └─────────┬───────────┘   └─────────┬───────────┘
                │                         │
      ┌─────────┴──── core (규범 도메인) ──┴─────────────┐
      │ model · structure(조문 파서) · effective(시행일) │
      │ ingest(적재·계보) · refs(참조) · quality          │
      └─────────┬──────────────────────────────────────┘
                │
      ┌─────────┴──── platform (공통 기반) ───────────────┐
      │ settings · db · outbox · storage(SeaweedFS)        │
      │ http(예의 지키는 클라이언트·요청 로그) · runs(실행 이력) │
      │ formats(HWP·HWPX·PDF 텍스트 추출, 형식 판별)          │
      └──────────────────────────────────────────────────┘
```

**의존 규칙** (테스트로 강제한다: `import-linter` 계약을 pytest에서 실행)

1. 화살표는 아래로만 간다. `platform`은 아무것도 import하지 않는다. `core`는 `platform`만 import한다.
2. **출처 모듈끼리는 서로 import하지 않는다.** `sources/alio`와 `sources/lawgo`는 서로를 모른다.
3. `core`는 출처를 모른다.
   - 출처 모듈이 시작될 때 자기 처리기를 `core.ingest`의 등록부(registry)에 올린다.
   - `core`가 출처 이름이나 출처 함수를 직접 부르지 않는다.
4. 내부규정 ↔ 법령 연계(§3A.5)는 lawgo 모듈의 **공개 읽기 API**(`sources.lawgo.api`)만 쓴다. 법령 테이블을 다른 모듈이 직접 조회하지 않는다.

### 1A.3 출처 모듈과 core 사이의 계약

출처 모듈은 두 가지만 core에 넘긴다. 이 계약이 바뀌지 않는 한, 출처 모듈 안은 마음대로 고쳐도 된다.

```python
# core/ingest/contract.py
@dataclass
class PreparedVersion:          # 출처가 만들어 넘기는 "적재할 한 판본"
    work_id: str                # 안정 id: kr/reg/KASI/여비규정, kr/law/010719
    work_kind: str              # INTERNAL_REG | 법률 | 대통령령 | …
    title: str
    institution_code: str | None
    source_document_id: int     # 보관 원본
    doc: ParsedDoc              # core.structure로 만든 조항 트리
    effective: Effective        # core.effective로 판정한 시행일
    external_ids: dict          # {"alio_seq": "186618"} | {"law_id": "010719", "mst": "253527"}
    links: dict                 # 원본 URL들 (§3A.6)

class SourceHandler(Protocol):
    topic: str                  # 이 출처가 남기는 outbox 주제
    group_field: str            # 묶음 처리 기준 필드 (seq, law_id)
    def prepare(self, conn, blob, payload: dict, today: date) -> PreparedVersion | None: ...

# core/ingest/registry.py
def register(handler: SourceHandler) -> None: ...
```

- `core.ingest.process_once`(지금의 `process.py`)는 등록부를 보고 대기 이벤트를 출처별 처리기에 넘긴다. 돌려받은 `PreparedVersion`을 적재한 뒤 계보·참조·품질·개정 이벤트를 처리한다.
- **outbox 주제와 payload는 버전이 있는 계약이다.**
  - `alio.file_fetched.v1 {seq, file_no, source_document_id}`
  - `lawgo.version_fetched.v1 {law_id, mst, source_document_id}`
  - 필드를 바꿀 때는 v2를 추가하고, 기존 이벤트를 다 소비할 때까지 v1 처리기를 남긴다.

### 1A.4 디렉터리 구조 (목표)

```
src/reg/
  platform/
    settings.py  db/  outbox.py  storage/  http.py(구 polite.py)  runs.py  sniff.py
    formats/      hwp.py  hwpx.py  pdf.py  convert.py(보기용 PDF 변환기 호출)
  core/
    model.py  structure/(parse.py, text.py)  effective.py
    ingest/       contract.py  registry.py  loader.py  process.py(구 process.py의 공통부)
    refs.py  quality.py  views/anchor.py
    migrations/   regulation 스키마 공통 테이블
  sources/
    alio/
      README.md         ALIO API 명세·응답 예시·알려진 특이점·사이트 변경 시 점검표
      client.py         findRuleList / findRuleDtl / rulefiledown 호출만 (구 collect/alio.py)
      sync.py           목록 지문 비교·상세·파일 다운로드·보관 (구 alio_sync.py)
      reconcile.py      폐지 감지 (§3.3, 신규)
      handler.py        SourceHandler 구현: 파일 → 추출 → core.structure → PreparedVersion
      ids.py            ALIO 규정 → work_id 규칙 (구 work_key_for_regulation)
      config.py         institutions.yaml 읽기, REG_ALIO_* 설정
      tasks.py          Airflow·CLI 진입점 (collect_institution, reconcile)
      migrations/       alio_rule, alio_rule_file
    lawgo/
      README.md         DRF 명세(lawSearch·lawService·lsHstInf), OC 키 정책, 응답 예시, 점검표
      client.py         DRF 호출만 (search, service, history, 페이지 넘김) (구 collect/lawgo.py)
      xml.py            법령 XML → 조문 트리 (구 structure/law_xml.py)
      mirror.py         law 스키마 적재: law_master / law_version / article (§3A.3)
      sync.py           일 변경분·전체 대조 (§3A.4) (구 law_sync.py 대체)
      urls.py           원본 링크 생성 (§3A.6) — 형식이 바뀌면 여기만 고친다
      api.py            다른 모듈용 공개 읽기 API: find_law(name), article_at(law_id, path, date), links(...)
      link.py           내부규정 참조 → 법령 조문 외래키 연결 (§3A.5)
      promote.py        인용된 법령을 regulation.work로 승격 + outbox 발행
      handler.py        SourceHandler 구현: 미러 판본 → PreparedVersion
      config.py         promote 대상(laws.yaml), REG_LAWGO_* (OC 키, 요청 간격)
      tasks.py          Airflow·CLI 진입점
      migrations/       law 스키마 전체 (별도 Alembic 이력, law.alembic_version)
  index/  graph/  alerts/  qa/  api/        (지금 구조 유지, 이름만 정리: search → index)
  cli.py           하위 명령을 모듈별로 등록: reg alio …, reg law …, reg process, reg index …
airflow/dags/
  reg_alio_daily.py  reg_law_daily.py  reg_law_full.py  reg_process.py  reg_publish.py  reg_notify.py  reg_maintenance.py
config/
  sources/alio.yaml     (구 institutions.yaml)
  sources/lawgo.yaml    (구 laws.yaml: 승격 대상 + 미러 범위)
  admins.yaml
tests/
  platform/  core/  sources/alio/  sources/lawgo/  index/  graph/  alerts/  qa/  api/
  sources/alio/fixtures/   실제 응답 JSON·HWP·PDF 표본
  sources/lawgo/fixtures/  실제 lawSearch·lawService·lsHstInf 응답 XML/JSON
```

### 1A.5 모듈별 소유권 (유지보수 단위)

| 모듈 | 소유 저장소 | 설정 | DAG | 바뀌는 계기 |
|---|---|---|---|---|
| `sources/alio` | `regulation.alio_rule`, `alio_rule_file` | `config/sources/alio.yaml`, `REG_ALIO_*` | `reg_alio_daily` | ALIO API·파일 형식 변경, 기관 추가 |
| `sources/lawgo` | **`law` 스키마 전체** | `config/sources/lawgo.yaml`, `REG_LAWGO_*` | `reg_law_daily`, `reg_law_full` | DRF 변경, OC 키, 링크 형식 |
| `core` | `regulation`의 work·버전·조항·참조·검수 테이블, outbox | — | `reg_process` | 조문 파서·시행일 규칙 개선 |
| `index` / `graph` / `alerts` | OpenSearch 색인 / Neo4j / 알림 테이블 | `REG_OS_*` / `REG_NEO4J_*` / `REG_SMTP_*` | `reg_publish`, `reg_notify` | 검색 튜닝, 그래프 모델, 알림 정책 |

- **테이블은 소유 모듈만 쓴다.** 예를 들어 `law` 스키마에 쓰는 코드는 `sources/lawgo` 안에만 있다.
- **마이그레이션도 모듈별 Alembic 이력이다.** 법령 테이블을 바꿔도 내부규정 마이그레이션 이력과 섞이지 않는다.
  - `reg db upgrade`가 platform → core → 각 출처 순으로 모두 실행한다.

### 1A.6 출처 모듈마다 갖출 것 (유지보수 장치)

1. **README**: 호출하는 엔드포인트, 파라미터, 응답 예시, 알려진 특이점(예: ALIO `bFiles`에 개정 이력 전체가 있음, HWP 서로게이트 쌍), 사이트가 바뀌었을 때 점검표.
2. **기록된 응답으로 하는 계약 테스트**: `fixtures/`의 실제 응답으로 client·파서를 테스트한다. 네트워크 없이 돈다.
3. **실연결 확인(canary)**
   - 일 배치 첫 태스크로 각 출처에 최소 요청 1~2개를 보낸다.
   - 응답 구조(필드명·형식)가 기대와 같은지 확인한다.
   - 다르면 전체 수집을 하지 않고 "ALIO 응답 구조 변경: `list[].title` 없음"처럼 원인이 보이는 메시지로 실패시킨다. 잘못된 데이터가 쌓이는 것을 막는다.
4. **모듈 버전**: 출처별 파서 버전(`alio.parser_version`, `lawgo.parser_version`)을 판본에 기록한다(§4.2). 한 출처의 파서만 바꿔도 그 출처만 재파싱할 수 있다.
5. **독립 실행**: `reg alio collect --institution KASI`, `reg law sync --date 2026-10-01`, `reg law full`, `reg law link`처럼 모듈별 CLI가 있다. DAG가 없어도 그 모듈만 돌려 볼 수 있다.

### 1A.7 지금 파일 → 새 위치

| 지금 | 새 위치 |
|---|---|
| `collect/polite.py`, `runs.py`, `sniff.py`, `archive.py`, `storage/blob.py`, `outbox.py`, `settings.py`, `db/` | `platform/` |
| `extract/hwp.py`, `hwpx.py`, `pdf.py`, `views/converter.py` | `platform/formats/` |
| `collect/alio.py`, `alio_sync.py`, `process.prepare_source_fetched`, `loader.work_key_for_regulation` | `sources/alio/` |
| `collect/lawgo.py`, `law_sync.py`, `structure/law_xml.py`, `process.prepare_law_fetched` | `sources/lawgo/` |
| `structure/model.py`, `parse.py`, `text.py`, `effective.py`, `load/loader.py`, `refs.py`, `quality.py`, `process.py`(공통부) | `core/` |
| `search/` | `index/` (이름 정리) |

- 옮기는 작업은 **동작을 바꾸지 않는 리팩터링**으로 먼저 끝낸다. 기존 테스트 196개가 그대로 통과하는 것을 기준으로 한다.
- 그 다음에 법령 미러·폐지 감지·Airflow 같은 새 기능을 올린다.

### 1A.8 나중에 더 떼어낼 때

다른 시스템(예: nst-nexus)도 법령 미러를 쓰게 되면, `sources/lawgo`를 uv workspace의 별도 패키지(`packages/law-mirror`)로 옮겨 독립 배포한다. 위 의존 규칙을 지키고 있으면 import 경로만 바뀐다.

## 2. Airflow 배치

### 2.1 배포

| 항목 | 설계 |
|---|---|
| 버전 | Airflow 3.x (구현 시점 최신 안정판으로 고정) |
| 실행 방식 | 이 저장소의 `infra/docker-compose.yml`에 `airflow-apiserver`, `airflow-scheduler`, `airflow-dag-processor`를 추가하고 **LocalExecutor**를 쓴다. 하루 수십~수백 개 태스크 규모라 Celery·Kubernetes는 과하다. |
| 메타데이터 DB | 공유 PostgreSQL(21055)에 별도 데이터베이스 `reg_airflow`를 만든다. `regulation` 스키마와 분리한다. |
| 웹 UI 포트 | **21062** (이 프로젝트 대역 21060~21069 안) |
| 이미지 | `nst-regulation/airflow`: 공식 이미지에 이 저장소의 `reg` 패키지를 설치한다. 코드가 바뀌면 이미지를 다시 빌드한다. |
| DAG 위치 | `airflow/dags/*.py` (저장소 안) |
| 비밀값 | `.env`의 `REG_*`를 컨테이너 환경으로 넘긴다. Airflow Connection에는 넣지 않는다. 모든 설정이 `reg.settings` 한 곳에 있게 하기 위해서다. |
| HWP→PDF 변환 | 지금은 `docker run nst-regulation/converter`를 호출한다. 두 가지 방법이 있다. **A안**: Airflow 컨테이너에 docker 소켓을 마운트한다. 변경이 가장 적지만 소켓 권한이 크다. **B안(권장)**: 변환기를 상주 서비스로 바꾸고 HTTP로 호출한다. → **결정 요청 D-2** |
| GPU(임베딩·LLM) | 사용자 Windows PC(192.168.0.2)에 의존한다. 꺼져 있으면 색인 태스크만 미루고, 나머지 단계는 진행한다. |

### 2.2 DAG 목록

| DAG | 일정 | 하는 일 | 동시 실행 |
|---|---|---|---|
| `reg_law_daily` | 매일 01:00 KST | 국내 현행 법령 변경분 미러링 → 내부규정 연계 → 인용 법령 승격 (§3A) | 1 |
| `reg_law_full` | 수동 (최초 1회), 이후 매주 일요일 00:00 대조 | 현행 법령 전체 목록과 미러를 대조해 누락·불일치 보정 | 1 |
| `reg_alio_daily` | 매일 02:00 KST | 기관 목록 갱신 → ALIO 수집(기관별 매핑) → 폐지 대조 | 1 (max_active_runs=1) |
| `reg_process` | Asset `regulation_raw` 갱신 시 + 매일 03:30 안전망 | outbox 소비, 품질 집계 | 1 |
| `reg_publish` | Asset `regulation_structured` 갱신 시 | 그래프·영향 분석·색인·게시·평가 | 1 |
| `reg_notify` | 매시 05분 | 알림 생성·메일 발송 | 1 |
| `reg_maintenance` | 매일 04:00 | 로그 정리, 옛 색인 삭제, 백업 확인 | 1 |
| `reg_backfill` | 수동 (conf: 기관, `rebuild` 여부) | 신규 기관 전체 수집, 파서 변경 후 재파싱 | 1 |

DAG를 하나로 묶지 않고 나눈 이유는 다음과 같다.
- 수집이 실패해도 이미 받은 파일의 파싱은 진행되어야 한다.
- 색인은 GPU가 켜져 있을 때만 가능하다.
- 알림은 매시간 돈다.
- 각 단계를 독립적으로 다시 실행할 수 있다.

### 2.3 태스크 공통 규칙

- **멱등**: 각 태스크는 outbox와 DB 상태만 보고 일한다. 같은 태스크를 두 번 돌려도 중복 적재가 없다(기존 코드의 유일 키와 지문 비교가 보장한다).
- **재시도**
  - 수집: 3회, 지수 백오프(5분부터)
  - 파싱: 1회. 파일 단위 실패는 outbox의 `attempts`에 기록되고 3회 실패하면 보류된다(기존 동작).
  - 색인: 6회, 30분 간격. GPU가 늦게 켜지는 경우를 고려했다.
- **Pool**
  - `alio_pool` = 2: ALIO 서버 예의. 기관 2곳까지만 동시에 수집하고, 요청 간격 1.5초는 기존 클라이언트가 지킨다.
  - `lawgo_pool` = 1
  - `gpu_pool` = 1: 색인과 평가가 GPU를 동시에 쓰지 않게 한다.
- **실행 이력**: 태스크마다 `fetch_run`(수집)이나 새 `pipeline_run`(§5.4)에 Airflow `dag_run_id`와 `task_id`를 기록한다. 화면이나 SQL에서 "어느 배치가 이 버전을 만들었나"를 추적할 수 있다.
- **실패 알림**: 태스크가 실패하면 `on_failure_callback`이 운영자 메일(Mailpit, 운영 SMTP)을 보낸다. 같은 날 같은 태스크는 한 번만 보낸다.
- **실행 시간 상한**
  - 수집: 기관당 60분
  - 파싱: 120분
  - 색인: 90분
  - 넘으면 실패 처리한다. 이미 커밋된 결과는 남는다.

### 2.4 DAG 코드 모양 (예시)

```python
# airflow/dags/reg_alio_daily.py
from airflow.sdk import Asset, dag, task
from pendulum import datetime

RAW = Asset("regulation_raw")

@dag(schedule="0 2 * * *", start_date=datetime(2026, 10, 1, tz="Asia/Seoul"), catchup=False,
     max_active_runs=1, default_args={"retries": 3, "retry_exponential_backoff": True})
def reg_alio_daily():
    @task
    def institutions() -> list[str]:
        from reg.sources.alio.tasks import active_institutions
        return active_institutions()            # 활성 기관 코드 목록

    @task(pool="alio_pool", execution_timeout=timedelta(minutes=60))
    def alio(code: str) -> dict:
        from reg.sources.alio.tasks import collect_institution
        return collect_institution(code)             # {"rules": n, "new_files": m, ...}

    @task
    def reconcile(stats: list[dict]) -> dict:
        from reg.sources.alio.tasks import reconcile
        return reconcile(stats)

    @task(outlets=[RAW])
    def done(stats: dict) -> dict:
        return stats

    done(reconcile(alio.expand(code=institutions())))

reg_alio_daily()
```

각 모듈의 `tasks.py`(§1A.4)는 얇은 진입점이다. 하는 일은 연결 열기, 실행 이력 기록, 결과 요약 반환뿐이다. CLI(`reg alio collect`)와 DAG가 같은 함수를 호출한다.

---

## 3. 수집 단계

### 3.1 ALIO 내부규정 (기관별)

1. **목록**: `findRuleList.json?type=apbaNa&word=기관명`으로 규정 목록을 받는다.
2. **변경 판정 (기존)**: 규정별로 목록 항목의 지문(제목·개정일·게시일 해시)을 `alio_rule.list_fingerprint`와 비교한다. 같고 파일도 이미 있으면 상세 조회를 건너뛴다. 매일 도는 배치에서 요청 수를 줄이는 핵심 장치다.
3. **상세**: `findRuleDtl.json?seq=`. `bFiles`에 개정 이력 파일이 모두 들어 있다.
4. **파일**: `rulefiledown.json?fileNo=`
   - 내용을 보고 형식을 판별한다(HWP·HWPX·PDF). 이미 받은 `fileNo`는 다시 받지 않는다.
   - 같은 내용(sha256)은 한 번만 저장한다.
5. **보관**
   - 원본은 SeaweedFS `regulation` 버킷의 `raw/{sha256 앞 2자리}/{sha256}`에 둔다.
   - 메타데이터는 `source_document`에 기록한다.
6. **이벤트**: 새 파일마다 outbox `regulation.source_fetched {seq, file_no, source_document_id}`를 남긴다.

예상 요청 수(일 배치, 기관 하나):
- 변경이 없는 날: 목록 1~3회
- 규정 하나가 바뀐 날: 상세 1회 + 파일 1~2회

출연연 전체로 넓혀도 하루 수백 회 안팎이다.

### 3.2 law.go.kr 법령

§3A로 옮겼다. 기존 `config/laws.yaml` 감시 방식은 법령 미러로 대체한다.

### 3.3 폐지 감지 (신규)

**폐지**는 기관이 규정을 없애는 것이다. 예: 천문연이 "구 출장여비 지급요령"을 "여비규정"에 통합하고 없앰. 그러면 ALIO 목록에서 그 규정이 사라진다.

지금은 이것을 알아채지 못한다. 없어진 규정이 DB에는 '현행'으로 남아, 검색과 질의응답이 이미 없어진 규정을 근거로 답할 수 있다.

설계:
- 기관 수집이 **정상 종료**되면, 그날 목록에 없던 규정에 `missing_since`(처음 사라진 날)를 기록한다.
- **연속 3일** 목록에 없으면 그 규정을 `폐지 후보`로 바꾸고 검수 화면에 띄운다.
- 사람이 "폐지 맞음"을 누르면 `폐지`가 된다.
  - 폐지된 규정은 현행 검색과 질의응답 근거에서 빠진다.
  - "작년 기준으로 어땠나" 같은 과거 기준일 질의에서는 계속 쓴다.
- 다시 목록에 나타나면 `missing_since`를 지우고 현행으로 되돌린다.

바로 폐지 처리하지 않는 이유: ALIO 장애나 일시적 누락으로 목록이 잘못 오는 날, 멀쩡한 규정이 통째로 사라지는 것을 막기 위해서다.

---

## 3A. 국내 법령 미러 (law.go.kr 현행 법령 전체, 별도 법령 DB)

### 3A.1 목표

- law.go.kr의 **현행 법령 전체**(법률·대통령령·총리령·부령 등 5,627건, 2026-10-02 조회)를 매일 받아 **별도 법령 DB**에 저장한다.
- 내부규정의 법령 인용("「국가연구개발혁신법」 제32조")은 법령 DB의 조문을 **외래키로 가리킨다**. 어느 화면에서든 그 조문으로 바로 갈 수 있다.
- 법령·조문마다 **원본 URL**(law.go.kr 법령 화면, 조문 화면, DRF 원문 XML)과 **보관 원본**(SeaweedFS의 XML)을 함께 둔다.
- 별표·서식(`target=licbyl`)도 받는다. 별표 본문(PDF·HWP 링크)과 서식 파일 링크를 조문처럼 `law.article`(경로 `annexN`, `formN`)에 둔다.
- 행정규칙(훈령·예규·고시·지침, `target=admrul`)은 2단계로 같은 구조에 추가한다. 출연연 규정이 자주 인용하는 과기정통부 고시·지침이 여기에 있다. 자치법규는 범위 밖이다.
- law.go.kr API 응답 확인(2026-10-02, 개발용 키): `law`, `eflaw`, `lsHstInf`, `licbyl`, `admrul`, `lsAbrv`, `lsJoHstInf`, `oldAndNew` 모두 응답함.

### 3A.2 저장 위치: nst-nexus와 분리된 전용 DB, 법령·내부규정 스키마 분리 (D-8 확정 방향)

현재는 이 프로젝트 테이블이 nst-nexus의 `nais` 데이터베이스 안 `regulation` 스키마에 있다. 같은 DB에 nst-nexus 스키마(audit, catalog, identity, project 등)가 함께 있다.

변경:
- 같은 PostgreSQL 서버(21055)에 **이 프로젝트 전용 데이터베이스 `nst_regulation`**을 만든다. nst-nexus의 `nais` DB와 완전히 분리된다(권한, 백업, 마이그레이션 모두 별도).
- 그 안에서 법령과 내부규정을 스키마로 나눈다.

| 스키마 | 담는 것 | 쓰는 모듈 |
|---|---|---|
| `law` | 국내 법령 미러: 법령·판본·조문 (§3A.3) | `sources/lawgo`만 |
| `regulation` | 내부규정: ALIO 목록·규범문서·버전·조항·참조·검수 | `sources/alio`, `core` |
| `ops` | 배치 실행 이력, outbox, 색인 release, 알림, 질의 로그 | 공통 |

- 법령과 내부규정이 같은 DB에 있으므로 `regulation.reference → law.article` 같은 **실제 외래키**를 걸 수 있다.
- 기존 `nais.regulation` 데이터는 `pg_dump -n regulation`으로 새 DB에 옮긴다. 앱은 접속 주소(`REG_DATABASE_URL`)만 바꾼다. 옮긴 뒤 `nais` DB에서 `regulation` 스키마를 지운다(확인 후).

### 3A.3 테이블 (`law` 스키마)

```
law.law_master    법령 1건 (법령ID 기준, 개정돼도 같은 행)
   ─< law.law_version   법령의 한 판본 (법령일련번호 MST 기준: 공포·시행·제개정구분)
        ─< law.article  조문 단위 (조·항·호·목, 부칙, 별표) 본문
        ─< law.attachment  별표·서식의 첨부 파일 링크 (HWP·PDF, 필요 시 SeaweedFS 보관)
   law.sync_run / law.change_log   일 배치 실행 이력, 그날 바뀐 법령 목록
```

| 테이블 | 키 | 주요 컬럼 |
|---|---|---|
| `law_master` | `law_id` (법령ID, 예: `010719` / 행정규칙은 `admrul:{행정규칙ID}`) | `name`, `name_abbr`, `family`(법령/행정규칙), `kind`(법률/대통령령/부령/훈령/예규/고시/…), `ministry`, `current_mst`, `status`(현행/폐지), `first_seen_at`, `last_synced_at`, `url`(법령 화면) |
| `law_version` | `mst` (법령일련번호) | `law_id`(FK), `promulgated_on`, `promulgation_no`, `effective_on`, `revision_kind`(제정/일부개정/타법개정/…), `is_current`, `source_document_id`(원본 XML, SeaweedFS), `xml_url`(DRF 원문), `html_url` |
| `article` | `id` | `mst`(FK), `law_id`, `path`(우리 경로 규칙: `a32.p1.i2`, 부칙 `supp@날짜`, 별표 `annexN`), `jo_code`(DRF 조문 코드 6자리, 예 `003200`), `label`(제32조), `heading`, `text`, `effective_on`, `url`(조문 화면) |

- `article`은 판본(MST)마다 저장한다. 그래야 과거 기준일 질의와 신구 비교가 된다.
- 바뀌지 않은 조문은 본문 해시로 판별해 저장 공간을 아낀다.
- 규모 예상:
  - 현행만 기준이면 조문 약 30~40만 행이다(법률·시행령·시행규칙 평균 수십 조).
  - 연혁을 쌓으면 해마다 수만 행씩 는다.

### 3A.4 일 배치 (`reg_law_daily`, 01:00) — 신청한 API 기준

**신청한 API** (2026-10-02, 사용자 신청):

| 대상 | 목록 | 본문 | DRF target | 규모 (2026-10-02) |
|---|---|---|---|---|
| 현행 법령 | XML | XML | `law` | 5,627건 |
| 현행 행정규칙 (훈령·예규·고시·지침) | XML | XML | `admrul` | 24,162건 |
| 법령 별표·서식 | XML | HTML | `licbyl` | 39,787건 |
| 행정규칙 별표·서식 | XML | HTML | `admbyl` | 84,341건 |

변경이력 API는 신청하지 않았다. 그래서 바뀐 것은 **목록을 최신순으로 받아 이전 상태와 비교**해서 찾는다.

**법령·행정규칙 (매일)**
1. `lawSearch.do?target=law&type=XML&sort=ddes`(공포일 내림차순, 실제로 동작 확인)로 첫 페이지부터 받는다.
2. 각 항목의 일련번호(MST)를 `law_version`에 있는지 확인한다. 공포일이 마지막 성공 동기화일보다 7일 넘게 이전인 페이지가 나오면 멈춘다.
   - 7일 여유는 늦게 등록되는 개정을 잡기 위해서다.
   - 보통 하루 1~3페이지(100건 단위)면 끝난다.
3. 새 MST마다 본문 XML(`lawService.do?target=law&MST=&type=XML`)을 받는다. 원본은 SeaweedFS에 보관하고, 조문을 `law.article`에 적재한다.
4. 행정규칙도 같은 방식이다: `target=admrul`, 정렬 기준은 발령일, 키는 행정규칙일련번호.

**별표·서식 (본문 HTML)**
- 별표 목록은 최신순 정렬이 되지 않는다(확인함). 그래서 **바뀐 법령·행정규칙을 기준으로** 받는다.
  - 3단계에서 새 판본이 생긴 법령마다 `target=licbyl&search=3&query={법령명}`(관련 법령명 검색, 동작 확인)으로 그 법령의 별표·서식 목록을 받는다.
  - 새 별표일련번호면 본문 HTML을 받는다.
- **HTML 처리**
  - 원본 HTML을 그대로 SeaweedFS에 보관한다.
  - 본문 텍스트를 추출해 `law.article`(경로 `annexN` / `formN`, 종류 별표·서식)에 넣는다.
  - HTML 안의 첨부 파일 링크(HWP·PDF)는 `law.attachment`에 URL로 기록한다. 파일 자체는 내부규정이 인용한 법령의 것만 받는다(용량 절약).
  - 표가 많은 별표는 텍스트 추출이 거칠 수 있다. 화면에는 원본 HTML·첨부 링크를 우선 보여준다.

**주간 전체 대조** (`reg_law_full`, 일요일 00:00):
- 법령 57페이지와 행정규칙 242페이지 목록을 끝까지 받아 미러와 비교한다(약 5분).
  - 일 배치가 놓친 것을 보정한다.
  - 목록에서 사라진 것은 `status = 폐지`로 바꾼다. 현행 API만 신청했으므로 목록에서 빠진 것이 폐지(또는 연혁화)다.
- 별표 전체 목록(licbyl 398페이지, admbyl 844페이지, 약 20분)은 월 1회 대조한다.

**최초 적재** (`reg_law_full` 수동 1회):
- 법령 5,627건 + 행정규칙 24,162건 본문 → 1초 간격이면 약 8~9시간이다. 이틀 밤에 나눠 돌린다.
- 별표·서식 12만여 건은 **내부규정이 인용한 법령·행정규칙의 것만** 먼저 받고, 나머지는 목록 정보(이름·링크)만 저장한다. 본문은 화면에서 처음 열 때 받아 캐시한다.

**과거 판본의 한계**:
- 연혁 API를 신청하지 않았으므로, 미러를 시작한 날 이전의 과거 판본은 없다. 시작일부터 매일 쌓인다.
- "2023년 기준 법령 조문" 같은 질의가 필요해지면 법령 연혁 API를 추가로 신청한다.
- 내부규정의 과거 판본은 ALIO에 개정 이력 파일이 모두 있으므로 영향이 없다.

**승격** (내부규정 연계 대상):
- 내부규정이 실제로 인용한 법령·행정규칙과 `config/sources/lawgo.yaml` 지정분만 `regulation.work`로 승격한다. 승격된 것은 검색·질의응답·개정 알림 대상이 된다.
- 승격된 것에 새 판본이 생기면 outbox `lawgo.version_fetched.v1`을 남긴다.
- 5,627 + 24,162건 전부를 검색·그래프에 넣지 않는다. 규정과 무관한 법령이 답변 근거를 흐리고 색인 비용만 커지기 때문이다.

**요청 예절과 키**: 운영 OC 키(서버 IP 116.43.250.15 등록), 요청 간격 1초 이상, `lawgo_pool` = 1.

### 3A.5 내부규정과의 연계 (외래키)

지금은 내부규정의 법령 인용(`regulation.reference`)이 법령명을 `regulation.work`의 제목과 맞춰 볼 뿐이다. 수집된 15개 법령 밖의 인용은 `law_seed`(미수집)로만 남는다.

변경:

| 연계 | 컬럼 (마이그레이션 0008) | 의미 |
|---|---|---|
| 참조 → 법령 | `regulation.reference.target_law_id` → `law.law_master.law_id` | 「국가연구개발혁신법」 → 법령 |
| 참조 → 조문 | `regulation.reference.target_law_article_id` → `law.article.id` | … 제32조 → 그 법령 **현행 판본**의 조문 |
| 규범문서 → 법령 | `regulation.work.law_id` → `law.law_master.law_id` | 승격된 법령 work와 미러의 연결 |
| 법령 버전 → 판본 | `regulation.work_version.law_mst` → `law.law_version.mst` | 뷰어의 법령 버전과 미러 판본의 연결 |

- **법령명 해석**: 정식 명칭 → 약칭(`law_master.name_abbr`) → 띄어쓰기·가운뎃점 정규화 순으로 맞춘다.
  - 「동법」, 「같은 법」처럼 앞 문장을 가리키는 표현은 바로 앞 인용으로 해석한다(기존 규칙).
  - 여러 법령에 맞거나 아무것에도 맞지 않으면 검수 큐(`REF_LAW_AMBIGUOUS`)로 보낸다.
- **조문 해석**: 인용 시점이 아니라 **그 내부규정 버전의 시행일에 유효했던 법령 판본**의 조문을 가리킨다. 현행 규정이면 현행 판본이다.
  - 법령이 개정돼 조문이 바뀌면 다음 연계 배치가 새 판본 조문으로 옮긴다. 이 변경이 개정 영향 분석의 입력이 된다.
- **법령이 폐지되거나 조문이 삭제된 경우**: 외래키는 마지막 판본의 조문을 그대로 가리킨다. 이 참조는 검수 큐(`REF_LAW_GONE`)와 개정 알림(삭제, 높음)으로 보낸다.

### 3A.6 원본 링크

모든 법령·조문에 세 가지 링크를 둔다. 화면에서는 "law.go.kr에서 보기", "원문 XML", "보관 원본"으로 노출한다.

| 링크 | 형식 | 예 |
|---|---|---|
| 법령 화면 (law.go.kr) | `https://www.law.go.kr/법령/{법령명}` (판본 지정 시 `/({공포번호},{공포일자})`) | `https://www.law.go.kr/법령/국가연구개발혁신법` |
| 조문 화면 (law.go.kr) | `https://www.law.go.kr/법령/{법령명}/제{N}조` (가지조는 `제{N}조의{M}`) | `…/국가연구개발혁신법/제32조` |
| 원문 XML (DRF) | `https://www.law.go.kr/DRF/lawService.do?target=law&MST={mst}&type=XML` (+ 조문 `&JO={jo_code}`) | 조회 시 OC 키가 필요해 서버가 중계한다 |
| 보관 원본 | 우리 API `/api/v1/files/{source_document_id}` (SeaweedFS) | 수집 당시 그대로의 XML |

- 법령명 URL은 사람이 보기 좋지만, 법령명이 바뀌면 깨질 수 있다. 그래서 MST 기반 DRF 링크와 보관 원본을 함께 둔다.
- 링크 형식은 구현할 때 실제 접속으로 다시 확인한다.

내부규정 뷰어의 표시:
- 법령 인용 문구(「…」 제32조)를 누르면 오른쪽 패널에 그 조문 본문이 뜬다. 패널에는 우리 법령 뷰어로 가는 링크와 law.go.kr 조문 링크가 함께 있다.
- 법령 쪽에서는 "이 조문을 인용하는 내부규정" 목록을 역방향으로 보여준다. 외래키 덕분에 조인 한 번이면 된다.

## 4. 파싱 단계

### 4.1 흐름 (기존 `process.py`)

```
outbox(source_fetched / law_fetched)
  → 규정 단위 묶음 (같은 seq·법령의 대기 이벤트를 한 번에, advisory lock)
  → 추출: HWP 5.0(OLE 레코드) | HWPX(XML) | PDF(pdfplumber, 머리글·쪽번호 제거) | 법령 XML
  → 구조 파싱: 장/절/조/항/호/목, 부칙(supp@날짜), 별표(annexN), 주석·개정 표시 분리
  → 시행일 판정: 부칙 > 개정이력 > ALIO 개정일 > 파일명
                (CONFIRMED / UNCERTAIN / CONFLICT, 불확실하면 검수 큐)
  → 적재 (§5): 버전 추가 → 계보 재계산 → 참조 해석 → 품질 검사 → 개정 이벤트
  → 보기용 PDF (HWP일 때, 이미 있으면 재사용)
```

- 실패는 파일 단위로 격리한다. 한 파일이 실패해도 같은 묶음의 다른 파일은 적재된다.
- 3회 실패한 이벤트는 보류되고 검수 큐에 남는다.

### 4.2 파서 버전과 재파싱 (신규)

- `work_version.parser_version`을 추가한다. `reg.structure` 패키지의 버전 문자열(예: `2026.10.2`)을 기록한다.
- 파서를 바꾸면 `reg_backfill` DAG를 `rebuild=true`로 수동 실행한다.
  - 원본이 SeaweedFS에 모두 있으므로 다시 수집하지 않고 재파싱만 한다(기존 `rebuild_all`).
  - 구조 테이블을 비우고 처음부터 적재한다.
  - 같은 날 OpenSearch·Neo4j도 다시 만든다.
  - 전체 재처리에서는 개정 이벤트가 생기지 않으므로 알림 폭주가 없다(구현·테스트됨).
- 재처리 중에도 검색과 질의응답은 이전 release 색인으로 계속 동작한다.

### 4.3 OCR (후속, M6)

- 글자 층이 없거나 깨진 PDF는 지금 `LOW_TEXT` 검수 작업으로만 남는다.
- 설계: 파싱 태스크가 `LOW_TEXT`를 만나면 outbox `regulation.ocr_needed`를 남긴다. 별도 태스크가 OCR 결과를 `source_document`의 파생 텍스트로 저장한 뒤 다시 파싱한다. 엔진 선택은 M6에서 정한다.

---

## 5. RDB 적재 (PostgreSQL `regulation` 스키마)

### 5.1 테이블 계층

```
[원천 목록]   institution ─< alio_rule ─< alio_rule_file >─ source_document (원본 파일, SeaweedFS 키)
[법령 DB]     law.law_master ─< law.law_version ─< law.article        (§3A, 별도 스키마, 현행 법령 전체)
                 ↑ FK                    ↑ FK              ↑ FK
              work.law_id      work_version.law_mst   reference.target_law_article_id
                 │
[목록 마스터] work (규범문서: 법령·내부규정 1건 = 1행, 안정 id 예: kr/reg/KASI/여비규정)
                 │
[버전]        work_version (시행일·상태·파서 결과) ─< amendment_history (개정 이력)
                 │
[조항]        provision (조항 계보: 번호가 바뀌어도 같은 조항)
                 ├─< provision_version (조항 판본: 경로·번호·제목·본문·주석)
                 └─  version_provision (버전 ↔ 판본 연결, 순서, 원문 위치 anchor)
              provision_change (버전 사이 변경: ADDED/MODIFIED/DELETED/RENUMBERED/ANNOTATION_ONLY)
                 │
[관계]        reference (조항 → 조항·규범문서, 6종 관계, 해석 상태, 근거 문구)
              law_seed (인용됐지만 미수집 법령)
                 │
[운영]        outbox · fetch_run · request_log · review_task · release · release_item
              change_impact · owner_assignment · notification · email_delivery · qa_log
```

### 5.2 주요 테이블 역할 (요약)

| 계층 | 테이블 | 키 | 한 행의 의미 | 쓰는 단계 |
|---|---|---|---|---|
| 원천 | `alio_rule` | `seq` | ALIO 규정 목록 1건(목록 지문·상세 JSON) | 수집 |
| 원천 | `alio_rule_file` | `file_no` | 규정에 첨부된 파일 1개(개정 이력별) | 수집 |
| 원천 | `source_document` | `id` (유일: source+sha256) | 받은 파일 1개(원본·보기 PDF 키) | 수집·파싱 |
| 마스터 | `work` | `id` | 규범문서 1건 | 파싱 |
| 버전 | `work_version` | `id` (`work@시행일`) | 규범문서의 한 시점 판본 | 파싱 |
| 조항 | `provision_version` | `id` | 조·항·호·목·부칙·별표 단위 본문 | 파싱 |
| 조항 | `version_provision` | (버전, 판본) | 그 버전에 들어 있는 조항과 순서 | 파싱 |
| 관계 | `reference` | `id` | 조항 하나가 다른 조항·문서를 가리키는 관계 1건 | 파싱 |

### 5.3 적재 방식

- **트랜잭션**: 규정 단위 묶음 하나가 트랜잭션 하나다. 버전 추가부터 개정 이벤트까지 한 번에 커밋한다. 중간에 실패하면 그 규정의 변경만 되돌아간다.
- **같은 조항 판본 재사용**: 본문 정규화 해시(`text_norm_hash`)가 같으면 기존 판본을 연결만 한다. 버전 2,000개, 조항 판본은 그보다 훨씬 적다.
- **참조**: 규범문서 단위로 지우고 다시 해석한다. 법령이 새로 수집되면 그 법령을 인용한 규정의 미해석 참조는 다음 배치에서 다시 해석한다.

### 5.4 추가할 것 (마이그레이션 0008)

| 변경 | 이유 |
|---|---|
| `law` 스키마: `law_master`, `law_version`, `article`, `sync_run`, `change_log` | 국내 법령 미러 (§3A) |
| `reference.target_law_id`, `reference.target_law_article_id`, `work.law_id`, `work_version.law_mst` (FK) | 내부규정 ↔ 법령 연계 (§3A.5) |
| `law_watch` 폐기 (`law.law_master`가 대체) | 법령 감시 일원화 |
| `work.status` (`ACTIVE` / `ABOLISHED_CANDIDATE` / `ABOLISHED`), `work.abolished_on` | 폐지 감지 (§3.3) |
| `alio_rule.missing_since` | 목록에서 사라진 날 |
| `work_version.parser_version` | 재파싱 대상 판별 (§4.2) |
| `pipeline_run` (`dag_id`, `run_id`, `task_id`, `started_at`, `finished_at`, `status`, `stats jsonb`) | Airflow 실행과 DB 결과 연결, 일 배치 요약 화면 |
| `embedding_cache` (`text_hash`, `model`, `vector real[]`, `created_at`, PK(`text_hash`, `model`)) | 변경분만 임베딩 (§6.2) |
| 조회 뷰 `v_regulation_master` | 기관·규정명·현행 버전·시행일·상태·조항 수·마지막 수집일. 목록 마스터를 한눈에 본다. |
| 조회 뷰 `v_provision_current` | 현행 조항 평탄화(규정, 경로, 번호, 제목, 본문). 분석·내보내기용 |

---

## 6. OpenSearch 색인

### 6.1 현재 (구현됨)

- **release 방식**
  1. 배치마다 새 색인 `nais-regulations-r{N}`을 만든다.
  2. 모든 버전의 청크를 넣는다.
  3. 검증한 뒤 alias `nais-regulations`를 바꿔 게시한다.
  - 실패하면 새 색인을 지우고 기존 alias는 그대로 둔다.
- **청크**: 조 단위가 기본이다. 긴 조는 항 단위로 나눈다. 필드는 규정·기관·시행 기간·경로·본문이다.
- **매핑**: nori 형태소 분석(BM25) + 1024차원 bge-m3 벡터(lucene HNSW)
- **검색**: 하이브리드(min_max 0.4/0.6) → bge-reranker
- **규모**: 청크 99,863개, 고유 텍스트 38,713개. 전체 재색인에 약 5분 걸린다(GPU).

### 6.2 일 배치용 변경

- **임베딩 캐시**: 청크 텍스트의 해시로 `embedding_cache`를 찾고, 없는 것만 GPU로 임베딩한다.
  - 하루 개정이 몇 건이면 새로 임베딩할 텍스트는 수십 개이므로, 재색인 시간이 대부분 bulk 적재 시간이 된다(예상 1~2분).
  - 임베딩 모델을 바꾸면 `model` 키가 달라지므로 캐시가 자연히 갈린다.
- **새 release 조건**: 마지막 게시 이후 `work_version`이나 `work.status`가 바뀌었을 때만 만든다. 변화가 없는 날은 건너뛴다.
- **품질 게이트 (`index_gate`)**: 다음을 모두 통과해야 alias를 바꾼다.
  - 청크 수가 직전 release보다 2% 넘게 줄지 않는다(대량 누락 방지).
  - 고정 질의 5개의 상위 결과에 기대 조문이 있다(스모크).
  - 실패하면 게시하지 않고 운영자에게 알린다. 이전 release가 계속 서비스된다.
- **GPU 불가**: `embed_check`에서 bge-m3에 응답이 없으면 색인 태스크를 재시도 상태로 미룬다(30분 간격, 최대 6회). 그 사이 검색은 이전 release로 동작한다.
- **정리**: 게시된 release와 직전 release 하나만 남기고 나머지 색인은 `reg_maintenance`가 지운다.

증분 업데이트(같은 색인에 문서만 추가·삭제) 대신 release 재생성을 유지하는 이유는 세 가지다.
- 질의응답 답변이 release id에 고정되어 재현 가능하다.
- 실패하면 alias를 그대로 두기만 하면 된다.
- 캐시를 쓰면 전체 재생성도 몇 분이면 끝난다.

---

## 7. Neo4j 그래프

### 7.1 현재 (구현됨)

- **투영**: PostgreSQL의 **현행 버전**을 그래프로 옮긴다(`reg graph sync`, 전체 재투영, 약 수십 초).
  - 노드: `RegInstitution`, `RegWork`, `RegProvision`
  - 관계: `ISSUES`, `HAS_PROVISION` + 참조 6종(`BASIS`, `DELEGATION`, `IMPLEMENTS`, `MUTATIS`, `EXCEPTION`, `CITATION`)
  - 현행에서 삭제된 조항을 가리키는 참조는 `missing` 노드로 남긴다. 그래야 삭제 영향을 찾을 수 있다.
- **용도**
  - 개정 영향 분석: 바뀐 조항에서 참조를 거꾸로 따라간다.
  - 향후 온톨로지 확장
  - 질의응답 답변 경로에는 쓰지 않는다.
- **잠금**: 재투영과 영향 분석은 PostgreSQL advisory lock 안에서 실행한다. 겹쳐 돌면 빈 그래프를 읽을 수 있기 때문이다(구현됨).

### 7.2 일 배치용

- `reg_publish`의 첫 태스크로 매일 재투영한다. 규모(조항 6만, 관계 1.4만)가 작아 증분 투영의 복잡도가 이득보다 크다.
  - 출연연 전체로 넓혀 조항 100만 이상이 되면 증분 투영으로 바꾼다. 바뀐 `work`만 지우고 다시 만드는 방식이다.
- 이어서 `alerts_scan`이 대기 중인 개정 이벤트를 소비해 영향을 기록한다. 실패한 이벤트는 다음 배치에서 다시 처리된다.

---

## 8. 기타 저장

| 저장소 | 내용 | 키·위치 | 보관 |
|---|---|---|---|
| SeaweedFS `regulation` (21066) | 원본 파일 | `raw/{sha[:2]}/{sha256}` | 영구 (재파싱의 근거) |
| 〃 | 보기용 PDF (HWP 변환) | `view/{sha256}.pdf` | 영구, 원본에서 다시 만들 수 있음 |
| PostgreSQL `request_log` | 외부 요청 로그(URL, 상태, 시간) | — | 90일 후 `reg_maintenance`가 삭제 |
| PostgreSQL `qa_log` | 질의응답 로그(개인정보 마스킹됨) | — | 1년 (운영 정책 확인 필요) |
| Airflow 로그 | 태스크 로그 | 컨테이너 볼륨 | 30일 |

백업:
- PostgreSQL은 nst-nexus의 백업 체계를 따르며, 확인이 필요하다.
- SeaweedFS 볼륨은 일 1회 스냅샷을 제안한다. → **결정 요청 D-5**

---

## 9. 운영

- **하루 요약**
  - `reg_publish`가 끝나면 그날 결과를 `pipeline_run`에 남기고, 운영자에게 메일 한 통을 보낸다.
  - 담는 내용: 수집 규정·파일 수, 새 버전 수, 실패·보류 수, 검수 큐 증가분, 개정 영향 수, 게시 release
- **실패 대응**
  - Airflow UI(21062)에서 실패한 태스크만 다시 실행한다(멱등이라 안전).
  - 보류된 파일은 검수 화면에 나온다.
- **신규 기관 추가**: `config/institutions.yaml`에 한 줄을 추가하고 `reg_backfill`(기관 지정)을 실행한다. 다음 날부터 일 배치에 포함된다.
- **수동 실행**: 지금처럼 CLI(`reg collect …`, `reg process --all`, `reg index build`)도 그대로 쓸 수 있다. Airflow가 내려가 있어도 운영할 수 있다.

---

## 10. 결정 요청

| # | 질문 | 제안 |
|---|---|---|
| D-1 | Airflow를 이 저장소 전용으로 띄울까요? (nst-nexus에는 Airflow가 없음) | **전용**, LocalExecutor, UI 21062, 메타 DB는 공유 PG의 `reg_airflow` |
| D-2 | HWP→PDF 변환기 호출 방식 | **B안**: 변환기를 상주 HTTP 서비스로 (docker 소켓 마운트 회피) |
| D-3 | 일 배치 시각 | 수집 02:00, 파싱은 수집 직후, 게시는 파싱 직후(대략 03:00~04:00 완료), 알림은 매시 |
| D-4 | 폐지 처리 | 연속 3일 목록에서 사라지면 폐지 후보로 두고, 사람이 확인하면 폐지 |
| D-5 | 백업 | PG는 nst-nexus 체계 확인, SeaweedFS는 일 1회 스냅샷 |
| D-6 | 운영자 실패·요약 메일 수신자 | **보류**: 당분간 메일 없이 Airflow UI(21062)와 하루 요약(`ops.pipeline_run`)으로 확인. 주소가 정해지면 설정만 추가 |
| D-7 | GPU PC가 꺼져 있을 때 | 색인만 미루고 이전 release로 서비스 (최대 3시간 재시도 후 실패 알림) |
| D-8 | 법령·내부규정 분리와 nst-nexus와의 분리 | **전용 DB `nst_regulation`** (nst-nexus `nais` DB와 분리) 안에 `law`(법령) / `regulation`(내부규정) / `ops`(운영) 스키마 (§3A.2) |
| D-9 | 법령 미러 범위 | **확정 (사용자 API 신청)**: 현행 법령·현행 행정규칙(목록·본문 XML), 법령·행정규칙 별표서식(목록 XML, 본문 HTML). 변경 감지는 목록 최신순 비교, 과거 판본은 미러 시작일부터 누적 (§3A.4) |
| D-10 | 검색·질의응답·그래프에 넣을 법령 | 내부규정이 인용한 법령 + `config/laws.yaml` 지정 법령만 승격 (전체는 법령 DB 조회·링크용) |
| D-11 | law.go.kr OC 키 | 운영 키 발급 필요 (사용자). 신청 시 서버 IP: 외부에서 보이는 공인 IP **116.43.250.15** (2026-10-02 확인, 내부 IP 192.168.0.3이 아님). 유동 IP일 수 있어 바뀌면 재등록 필요 |
| D-12 | 모듈 분리 수준 | **한 저장소 안의 하위 패키지 + import 규칙 테스트**(§1A). 다른 시스템이 법령 미러를 쓰게 되면 그때 별도 패키지로 |

---

## 11. 구현 순서 (승인 후 계획서 작성)

0. 모듈 재배치 리팩터링 (§1A.7, 동작 변경 없음, 기존 테스트 전부 통과) + import 규칙 테스트 + 출처별 README·계약 테스트
1. 마이그레이션 0008(§5.4)과 모듈별 `tasks.py` 진입점. CLI와 DAG가 같은 진입점을 쓰도록 정리한다.
1A. 법령 미러: `law` 스키마, 변경 목록·전체 목록 수집기, 조문 적재, 연계(외래키)·승격, 원본 링크 API·뷰어 패널 (§3A)
2. 임베딩 캐시와 품질 게이트, 변화 없는 날 건너뛰기 (§6.2)
3. 폐지 감지 (§3.3)
4. Airflow 배포(compose, 이미지, 메타 DB)와 DAG 6개, Pool, 실패 콜백
5. 변환기 서비스화 (D-2 결정에 따라)
6. 하루 요약 메일, `reg_maintenance`
7. 실연결: 1주일 시범 운영 → 실패율·소요 시간 측정 → 보고서
