# M7 그래프·검색 재설계 (Neo4j 법령 구조 그래프 · OpenSearch 조항호목 검색)

- 작성: 2026-10-03 · 상태: **사용자 지시로 즉시 구현**
- 계기 (사용자):
  - "Neo4j는 graphdb를 활용해서 법률 규정을 잘 쓰기 위함이고 OpenSearch는 검색을 잘하기 위함인데, 제대로 만들라."
  - "OpenSearch도 조항호목으로 잘 나눠서 저장하고 특정 조에 대해 검색해서 나오게."
- 지금의 한계:
  - Neo4j는 현행 조항과 참조선만 둔 개정 알림용 보조 그래프다.
  - OpenSearch는 조 덩어리로 색인해서, 항·호·목 단위 검색과 번호 직접 조회를 할 수 없다.

## 0. 배치

| 구성 | 위치 | 비고 |
|---|---|---|
| OpenSearch (전용) | GPU PC `192.168.0.2:8005` | 2.19.1 + nori + knn, 힙 8GB, 보안 플러그인(HTTP). 계정 `reg_app`(`.env` `REG_GPU_OS_URL`). 설치 파일은 `infra/gpu-opensearch/` (설치 완료) |
| Neo4j (전용, 이전) | GPU PC `192.168.0.2:8006`(bolt) / `8007`(브라우저) | 5.26 community, heap 4GB + page cache 8GB. `infra/gpu-neo4j/`. 이 서버의 Neo4j는 전환 후 내린다 |
| PostgreSQL | 이 서버 (그대로) | 기준 데이터. 그래프·색인은 모두 PostgreSQL에서 다시 만든다 |

- 방화벽: GPU PC는 192.168.0.3만 허용한다.
- 사용자가 보는 화면(대시보드, Neo4j 브라우저)은 이 서버가 중계한다.
  - 21069 → GPU PC OpenSearch Dashboards
  - 21065·21064 → GPU PC Neo4j
- nst-nexus는 기존 공유 OpenSearch(`nais-opensearch-1`)를 그대로 쓴다. 이 프로젝트의 옛 색인(r1~r10)은 전환을 확인한 뒤 공유 클러스터에서 지운다.

## 1. Neo4j: 법령·규정 구조 그래프 (트랙 M7-G)

### 1.1 모델

**노드**

| 라벨 | 키 | 주요 속성 |
|---|---|---|
| `Institution` | `code` | `name`, `aliases` |
| `Work` | `id` | `title`, `kind`, `family`(reg/law/admrul), `status`, `institution` |
| `Version` | `id` | `effective_from`, `effective_to`, `state`(CURRENT/HISTORICAL/FUTURE), `amendment_kind`, `promulgated_on` |
| `Provision` + 단위 라벨(`Article`/`Paragraph`/`Item`/`Subitem`/`Annex`/`Form`/`Supplement`/`SuppArticle`/`Chapter`/`Section`) | `pv_id` (= `provision_version.id`, 본문 판본) | `path`, `label`, `full_label`("여비규정 제27조 제1항"), `heading`, `text`, `lineage`(= `provision.id`) |
| `Term` | `work_id + name` | `name`, `definition` (정의 조항에서 추출) |

**관계**

| 관계 | 의미 |
|---|---|
| `(Institution)-[:ISSUES]->(Work)` | 기관이 규범문서를 냄 |
| `(Work)-[:HAS_VERSION]->(Version)` | 판본 |
| `(Version)-[:NEXT_VERSION]->(Version)` | 시행일 순서 |
| `(Version)-[:CONTAINS {ord}]->(Provision)` | 그 판본의 최상위 단위(장·조·부칙·별표) |
| `(Provision)-[:CONTAINS {ord}]->(Provision)` | 조→항→호→목 계층 (`parent_path` 기준) |
| `(Provision)-[:AMENDED_TO {kind, from_version, to_version}]->(Provision)` | 판본 간 계보 (`provision_change`: MODIFIED/RENUMBERED/ANNOTATION_ONLY) |
| `(Provision)-[:ADDED_IN]->(Version)` / `(Provision)-[:DELETED_IN]->(Version)` | 신설·삭제 |
| `(Provision)-[:BASIS\|DELEGATION\|IMPLEMENTS\|MUTATIS\|EXCEPTION\|CITATION {evidence, resolution}]->(Provision\|Work)` | 참조 (정확한 항·호 단위) |
| `(Provision)-[:DEFINES]->(Term)` | 정의 조항(대개 제2조 각 호)이 용어를 정의 |
| `(Provision)-[:USES]->(Term)` | 같은 규범문서에서 그 용어를 쓰는 조항 |

**참조 대상 판본**
- 출처 판본의 시행일에 유효했던 대상 판본의 조항을 가리킨다.
- 그런 판본이 없으면 대상의 현행 판본을 가리킨다.

**법령**
- 법령·행정규칙도 `regulation.work`(`kr/law/…`, `kr/admrul/…`)로 승격된 것은 같은 모델에 들어간다.
- 법령 미러(`law.article`)가 적재되면 `(:LawArticle {law_article_id})`를 `Provision`과 같은 방식으로 넣는다. 지금은 키 대기 상태다.

### 1.2 동기화
- 전체 재투영: `reg graph rebuild`. 모든 판본을 배치(UNWIND 5,000)로 넣는다.
- 규범문서 단위 증분: `reg graph sync --works …`. 그 Work의 하위 그래프를 지우고 다시 넣는다. Airflow `reg_publish`가 그날 바뀐 Work만 넣는다.
- 제약·인덱스:
  - `Provision.pv_id`, `Version.id`, `Work.id`는 UNIQUE
  - `Provision(path)`, `Provision(full_label)`에 인덱스
  - `Term(name)`에 전문 인덱스
- `graph_lock`(PostgreSQL advisory lock)은 유지한다.

### 1.3 그래프를 쓰는 곳
1. **질의응답 근거 확장(그래프 RAG)**: `reg.graph.expand(pv_ids, as_of)`
   - 근거 조항에서 시작해 아래 방향으로 따라간다.
     - EXCEPTION·MUTATIS·BASIS·DELEGATION·IMPLEMENTS·CITATION을 따라 1~2단계
     - 근거에서 쓰인 Term의 DEFINES 조항
     - 상위 조(문맥)
   - 결과는 근거 후보와 관계 이유("예외 조항", "용어 정의") 목록이다. 기존 `qa.evidence.expand`가 PostgreSQL 대신 이것을 쓴다.
2. **관계도 API**: `GET /api/v1/graph/neighborhood?pv=…&depth=1|2`
   - 노드·엣지 JSON을 돌려준다.
   - 웹 뷰어에 "관계도" 탭을 단다. 이 조가 무엇에 근거하고, 무엇이 이 조를 인용하고, 용어 정의는 무엇이며, 판본 계보는 어떤지를 보여준다.
3. **조항 이력 API**: `GET /api/v1/graph/lineage?pv=…`
   - AMENDED_TO 사슬, 즉 시행일별 본문 변화를 돌려준다.
4. **개정 영향 분석**: `reg.alerts.impact`를 새 모델로 옮긴다.
   - 원인 조항에서 역방향 참조와 DELEGATION 사슬을 따라간다.
   - 기존 계약(ALERT_CAUSE_PREFIXES, 심각도, 묶음)은 유지한다.

## 2. OpenSearch: 조·항·호·목 단위 검색 (트랙 M7-S)

### 2.1 문서 모델 (색인 `reg-provisions-r{N}`, 별칭 `reg-provisions`)
- **문서 1개 = 조항 판본 1개(provision_version)를 그 판본(work_version)에서 본 것.** 조·항·호·목·별표·서식·부칙·부칙조를 모두 포함한다. 장·절은 문맥으로만 쓴다.
- 모든 dated 판본을 넣는다(과거 기준일 검색용). 벡터는 **현행 판본의 조·항·별표 조각**에만 넣는다(공간 절약). 과거 판본은 BM25로만 찾는다.

| 필드 | 형식 | 설명 |
|---|---|---|
| `doc_id` | keyword | `version_id|path` |
| `work_id`, `version_id`, `path`, `parent_path`, `article_path` | keyword | 위치 |
| `unit` | keyword | article/paragraph/item/subitem/annex/form/supplement/supp_article |
| `article_no`, `article_branch`, `paragraph_no`, `item_no` | integer | 번호 직접 조회용 ("제27조의2 제1항 제3호" → 27, 2, 1, 3) |
| `subitem` | keyword | 목("가") |
| `label` / `full_label` | keyword + text | "제1항" / "여비규정 제27조 제1항" |
| `heading` | text(ko) | 조 제목 |
| `title` | text(ko) + keyword + search_as_you_type | 규정명 (자동완성) |
| `institution`, `institution_name`, `institution_aliases`, `family`, `work_kind` | keyword (+text) | 필터·집계 |
| `effective_from`, `effective_to`, `version_state` | date/keyword | 기준일 필터 |
| `text` | text(ko, 동의어 분석기) | 그 단위 본문 |
| `article_text` | text(ko) | 소속 조 전체 본문 (문맥 검색·하이라이트용; 조 문서에만 저장하고 하위는 생략 가능) |
| `breadcrumb` | text | "한국천문연구원 > 여비규정 > 제5장 > 제27조(출장증빙의 제출) > 제1항" |
| `embedding` | knn_vector 1024 (lucene hnsw, cosine) | 현행 판본 조·항·별표 조각만 |
| `annex_image` | keyword | 별표 이미지 API 경로 (있으면) |

- **분석기**
  - `ko`: nori mixed
  - `ko_syn`: `ko` + synonym_graph(`config/search_synonyms.txt`). 예: 출장비↔여비, 지출결의↔정산, 연차↔연가
  - 사용자 사전(`config/search_userdict.txt`): 기관 약칭, 규정 용어
- 긴 단위(>1,200자)는 `#n` 조각으로 나눈다. M6의 창 분할 규칙을 그대로 쓴다.

### 2.2 검색 API (`reg.search`)
1. **조문 번호 직접 조회**: `parse_citation("천문연 여비규정 27조 1항")`
   - 결과: `{institution: KASI, title: "여비규정", article: 27, paragraph: 1}`
   - 이것으로 term 조회를 한다. 질문이 번호 조회 형태면 먼저 돌려준다.
2. **하이브리드 검색**
   - BM25(`text^3`, `heading^2`, `full_label`, `breadcrumb`)와 knn(현행)을 합친다(min_max, 0.4/0.6).
   - 리랭크한다.
   - **조 단위로 묶어**(collapse `article_path`+`version_id`) 조마다 맞은 하위 단위(inner_hits)와 하이라이트를 돌려준다.
3. **필터**: 기관(코드·이름·약칭), 규정 종류, 단위, 기준일, 현행만
4. **집계**: 기관별·규정별 건수(facets)
5. **자동완성**: `GET /api/v1/search/suggest?q=여비` → 규정명

### 2.3 화면·질의응답
- 검색 화면:
  - 결과를 조 단위 카드로 보여주고, 맞은 항·호를 음영으로 강조한다.
  - 기관·종류 필터와 집계를 둔다.
  - 번호 조회 결과를 맨 위에 둔다.
- 질의응답:
  - 근거를 **항 단위**로 고르고, 그래프 확장(1.3)으로 예외·정의·인용 조문을 덧붙인다.
  - 근거 카드에서 해당 항을 강조한다.

## 3. 품질 기준
- 번호 조회: 평가 세트의 모든 기대 조문을 "규정명 + 조 + 항"으로 넣으면 1위로 나와야 한다.
- 질의응답 평가(`eval/qa_cases.yaml`): 인용 정확도 0.833 → **≥ 0.90**, 결론 정확도 1.0 유지
- 검색 p95 < 1.5초 (GPU PC 왕복 포함)
- 그래프 확장: 정의 조항이 있는 규정에서 용어 질문의 근거에 정의 조항이 포함된다(테스트 사례 5개).

## 4. 트랙과 순서
- **M7-G (그래프)**와 **M7-S (검색)**는 병렬로 진행한다. 둘 다 PostgreSQL만 읽고 서로를 import하지 않는다.
- **M7-Q (질의응답·화면 통합)**은 G·S가 끝난 뒤 메인 세션이 한다.
- 실서버 전환:
  1. GPU PC에 Neo4j를 설치한다.
  2. 그래프를 전체 재투영한다.
  3. 새 색인을 만들고 품질 확인을 거쳐 게시한다.
  4. `REG_OS_URL`을 GPU 클러스터로 바꾼다.
  5. 평가를 다시 돌린다.
  6. 옛 색인을 정리한다.
