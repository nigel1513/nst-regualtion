# NST 규정·법령 플랫폼 + NAIS 기술자료 (목차)

- 기준일: 2026-10-03 · 모든 수치는 작성 시점에 실제 DB·색인·그래프에서 다시 센 값이다 (각 문서에 쓴 SQL·쿼리가 함께 있다).
- 비밀번호·키 값은 문서에 넣지 않았다. 위치는 서버의 `/data/project/nst-regulation/.env`, `/data/project/nst-nexus/.env`.

## 1. 두 시스템 한눈에

| 구분 | 규정·법령 플랫폼 | NAIS (연구데이터 플랫폼) |
|---|---|---|
| 주소 | 웹 http://192.168.0.3:21060 · API :21061 · Airflow :21062 · Dashboards :21069 · Neo4j 브라우저 :21065 | 포털 http://192.168.0.3:21051 (gateway) |
| 저장소 | `/data/project/nst-regulation` (GitHub `nigel1513/nst-regualtion`) | `/data/project/nst-nexus` |
| 하는 일 | 25개 출연연·NST 내부규정 수집(ALIO) + law.go.kr 법령 미러 → 조·항·호·목 구조화 → 뷰어·검색·질의응답·개정 알림 | 연구데이터 업로드·검증·발행·검색, 프로젝트 |
| RDB | PostgreSQL 16 DB `nst_regulation` (스키마 regulation / law / ops) | 같은 PostgreSQL 서버의 DB `nais` |
| 검색 | GPU PC OpenSearch `reg-provisions` → r16 | 같은 클러스터 `nais-datasets` → v2 |
| 그래프 | GPU PC Neo4j (법령·규정 구조 그래프) | 같은 DB에 `Nais*` 라벨로 넣을 계획 |
| 배치 | Airflow 3.3.2, DAG 10개 | Dramatiq worker + index_queue |

```mermaid
flowchart LR
  subgraph SRV[서버 192.168.0.3]
    PG[(PostgreSQL 21055<br/>nst_regulation · nais)]
    API[규정 API 21061] --- WEB[규정 웹 21060]
    AF[Airflow 21062]
    S3[(SeaweedFS 21066)]
    NX[NAIS gateway 21051<br/>web·api·worker·keycloak·opa]
    GW[OpenSearch 중계 21056]
    DB2[Dashboards 21069]
    NP[Neo4j 중계 21064/21065]
  end
  subgraph GPU[GPU PC 192.168.0.2 · RTX 4090]
    LLM[EXAONE 3.5 7.8B :8001]
    EMB[bge-m3 :8002]
    RR[reranker :8003]
    OCR[MinerU :8004]
    OS[(OpenSearch :8005)]
    NEO[(Neo4j :8006/8007)]
  end
  ALIO[ALIO] --> AF
  LAW[law.go.kr] -. 키 승인 대기 .-> AF
  AF --> PG & S3 & OCR & EMB & OS & NEO
  API --> PG & OS & NEO & LLM & EMB & RR
  NX --> PG & OS
  GW --> OS
  DB2 --> OS
  NP --> NEO
```

## 2. 문서 목록

| 문서 | 내용 |
|---|---|
| [02-data-loading.md](02-data-loading.md) | **데이터 적재 상세**: 출처(ALIO·law.go.kr) → 원본 보관 → 변환·OCR → 조·항·호·목 파싱·계보 → 참조 해석 → 색인·그래프·알림 반영, Airflow DAG 10개, 수동 명령과 런북, 현재 적재 수치 |
| [03-rdb.md](03-rdb.md) | **PostgreSQL**: 34개 테이블·뷰의 모든 필드·제약·인덱스와 쓰는 쿼리, 설계 근거, ERD, 현황 |
| [04-search-graph.md](04-search-graph.md) | **OpenSearch**(필드 42개, 분석기, 하이브리드 검색, 릴리스 모델) + **Neo4j**(노드·관계·속성, 동기화, 근거 확장·관계도·이력·영향 분석 쿼리), 현황 |
| [05-services-infra-e2e.md](05-services-infra-e2e.md) | **서비스·인프라·E2E**: 서버·GPU PC 구성과 포트, 버전, API 33개, 화면별 E2E 흐름(조회·참조 팝업·검색·질의응답·개정 알림·일일 배치), 질의응답 평가, 운영, 테스트 |
| [NAIS 기술 문서](../../../nst-nexus/docs/tech/nais-technical-reference.md) (`/data/project/nst-nexus/docs/tech/nais-technical-reference.md`) | **NAIS**: 구성, 모듈, DB 스키마, `nais-datasets` 색인, 데이터 적재(업로드 → 검증 → 발행 → 준비도 → 색인), E2E, 현황, 계획 |

## 3. 확인된 할 일과 처리 결과 (2026-10-03 갱신)

| # | 내용 | 처리 | 출처 문서 |
|---|---|---|---|
| 1 | law.go.kr OC 키 승인 대기 — 법령 DAG 3개 일시정지, `law` 스키마 0건 | **대기** (키 승인 후 `reg law full`) | 02, 03 |
| 2 | law.go.kr 법령을 현행 전체로 받던 코드 | **해결**: 필요한 법령만 (설정 20 + 규정이 인용한 법령 1,099 + 그 시행령·시행규칙, 대상 이름 2,718). `reg law targets`로 목록 확인 | 02 |
| 3 | 같은 규정 안 미해석 참조 | **해결**: 해석기·추출기 수정(자기 규정으로 잘못 연결된 약 1,200건 교정 포함), `reg refs reresolve` + 매일 `reg_process`에서 자동 재해석. 본문 속 `【별지 …】`·`■ [별지 …]` 제목 인식(파서 2026.10.7)으로 별표·서식 참조 약 4,100건 추가 해결 예상 — 전체 재파싱 2026-10-03 21:02 시작. 남은 미해석은 대부분 대상이 실제로 없는 경우(원본에 별표 없음 9,277, 다른 판본에만 있음 5,814) | 02 |
| 4 | 인덱스 보강 | **해결**: 마이그레이션 0009 (`provision_change_work`, `reference_work`, `review_task_target`), ALIO 일련번호 조회가 부분 인덱스 `work_alio_seq`를 쓰도록 수정 | 03 |
| 5 | 정리 대상: `regulation.law_watch`, `nais` DB의 옛 `regulation` 스키마, 옛 색인 `nais-regulations-r14`(8.4GB) | **해결 (2026-10-03 삭제)**: 셋 다 삭제, `law_watch`는 마이그레이션 0010에도 반영. 멈춘 기록(pipeline_run 162 → failed, release 10 → FAILED, release 14 → RETIRED)도 정리 | 03, 04 |
| 6 | 질문 속 기관명 검색 | **해결**: 원인은 리랭커 순위. 기관을 알면 짚은 조문을 1위로, 조문 없이 기관명만 있어도 그 기관으로 좁힘 | 04, 05 |
| 7 | GPU PC OpenSearch 데모 계정·앱 계정 all_access | **보류 (사용자 결정: 지금은 필요 없음)** | 04 |
| 8 | OCR `gpu_pool`, `.xls` 오인식, 서식 라벨 | **해결**: OCR을 `gpu_pool`에, OLE Office 파일(xls·doc)은 HWP로 받지 않음, 그래프에서 서식은 `Form`(10,950) 별표는 `Annex`(14,209) | 02, 04 |
| 9 | KRIBB 수집 실패 | **해결 확인 대기**: 수정 코드가 Airflow 이미지에 들어감. 재파싱 후 자동 수집 재개 때 확인 | 03 |
| 10 | NAIS 포털 웹 mock 모드 | NAIS 세션 담당 (알림 완료) | NAIS |
| 11 | "중중중" 반복 글자 | **해결**: 같은 길이로 3번 이상 반복된 글자만 합침 (실데이터 3개 규정 11개 조문) | 02 |
