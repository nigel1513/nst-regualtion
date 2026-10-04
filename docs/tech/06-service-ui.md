# 06. 서비스 화면 (2026-10-04 개편)

- 설계: `docs/superpowers/specs/2026-10-03-service-ui-redesign.md` · 스토리보드: https://claude.ai/artifact/GcAyzq4MZMBp6131Qv3Avd
- 목적: 각 기관 행정원·연구자가 규정을 쉽게 찾고, **우리 기관 규정을 다른 기관의 같은 내용과 비교해** 더 나은 운영 방식을 알게 한다.
- 디자인 기준: NAIS 디자인 시스템 방향 A(`/data/project/nst-nexus/docs/superpowers/specs/2026-10-01-ui-design-system.md`) — Radix slate/indigo 토큰, Pretendard, 잉크색 주 버튼, 반경 6/10/14, "LLM이 만든 느낌" 금지 목록. 화면 점검 스크린샷: `docs/reports/ui-2026-10-03/`.

## 1. 화면과 API

| 화면 | 경로 | 하는 일 | API |
|---|---|---|---|
| 로그인 (목업) | `/login` | 계정을 고르거나 이름·기관·역할을 적는다. 그 사람의 기관이 "우리 기관"이 되어 홈·규정 찾기·기관 비교가 미리 걸러진다(권한 차이 없음). 세션 쿠키 `nst-session`, 없으면 `src/proxy.ts`가 로그인 화면으로 보낸다. 실제 서비스에서는 기관 SSO로 바꾼다 | — |
| 앱 셸 | 모든 화면 | 사이드바(접기·모바일 시트, 우리 기관 표시, 사용자·로그아웃), 브레드크럼, ⌘K/Ctrl+K 명령 팔레트(조문 찾기·규정 제목·이동·도우미에게 묻기), 다크 모드 | `GET /api/v1/suggest`, `GET /api/v1/search/lookup` |
| 홈 | `/` | 우리 기관: 현황, **다른 기관과 다른 점**, 최근 바뀐 규정(바뀐 조문 요약), 주제별 규정 수 · 전체: 기관별 현황 표 | `GET /api/v1/home?inst=`, `GET /api/v1/compare/divergences?inst=` |
| 규정 찾기 | `/regulations` | 기관·주제·종류·상태 필터(각 축 개수), 목록 / 기관별 묶기, 정렬, 페이지 | `GET /api/v1/regulations?q=&inst=&topic=&kind=&status=&sort=&page=` |
| 규정 보기 | `/regulations/[...id]` | 탭 본문·개정 이력(판본 간 글자 비교: 삭제 빨강·추가 초록)·관계도·별표·서식, 목차, 참조 팝업, 오른쪽 **다른 기관의 같은 조항**(의미 검색, 비교값 같음/다름) | `GET /api/v1/provision/similar?pv=`, `GET /api/v1/provision/compare?pv=`, 기존 규정·참조·그래프 API |
| 기관 비교 | `/compare`, `/compare?topic=` | 주제별 항목 × 기관 표(우리 기관 첫 열, 다른 칸 노란색, 다수 값), 차이만 보기, **조문 나란히**(인용·값 강조), CSV | `GET /api/v1/topics`, `GET /api/v1/compare`, `GET /api/v1/compare/provisions`, `GET /api/v1/compare/export.csv` |
| 규정 도우미 | `/assistant` (`/search`, `/qa`는 이리로) | 검색 + 질의응답 통합 챗봇. 범위 전체/기관 선택, 질문 속 기관 이름으로 좁힘, 조문 찾기·질문·여러 기관 비교, 모든 근거는 원문 그대로의 인용, 후속 질문, 멈추기 | `POST /api/v1/chat` (SSE, `?stream=false`) |
| 검수 | `/review` | 기관·규정·위치·문제·해야 할 일·담당·상태, 법령 적재 대기 분리, 내 이름(localStorage), 담당 지정(여러 건), 처리·문제 없음·보류·다시 열기 | `GET /api/v1/review-tasks`, `POST …/{id}/assign|resolve|dismiss|hold|reopen`, `POST …/bulk-assign` |

## 2. 새 데이터

| 테이블 | 마이그레이션 | 내용 |
|---|---|---|
| `regulation.work_topic` | 0011 | 규정 ↔ 주제(최대 2개). 제목 규칙 → 목적 조문 규칙 → 임베딩 유사도. 주제 정의는 `config/topics.yaml`(20개) |
| `regulation.compare_cell` | 0011 | 주제 · 비교 항목 × 기관의 값. 하이브리드 검색으로 근거 조문 후보 → EXAONE이 값·인용 추출 → 인용이 원문에 그대로 있어야 저장. `method='manual'` 행은 재생성에도 남는다 |
| `regulation.review_decision` | 0013 | 검수 결정(담당·상태·결정). 재파싱으로 `review_task`가 다시 만들어져도 트리거가 결정을 되살린다 |

- 비교 항목(1차 21개): 여비·출장(증빙 제출 기한, 정산 기한, 일비, 국내 숙박비 상한, 국외출장 사전 심의), 회계·재무, 계약·구매, 인사·복무, 연구관리, 보안 — `config/topics.yaml`에서 늘린다.
- 2026-10-04 실데이터: 주제 분류 3,829개 규정(제목 3,337 · 목적 206 · 임베딩 286), 표본 정확도 0.93~0.95. 비교값 525칸 중 값 328칸, 표본 25칸 수기 점검 약 0.9.

## 3. 배치

- `reg_publish` DAG: … → `index_publish` → `topics_classify`(새 규정만) → `compare_build`(새 판본이 들어온 기관만, `gpu_pool`).
- CLI: `reg topics classify [--all]`, `reg topics eval`, `reg compare build [--topic] [--inst] [--changed] [--dry-run]`, `reg fix-titles`.

## 4. 알려진 한계

- 비교값은 자동 추출이라 틀릴 수 있다(예: 일반 한도 대신 특례 금액). 칸마다 근거 조문 링크와 원문 인용이 있으니 확인하고 쓴다. 검수 화면에서 고치는 기능(수기 값 `manual`)은 후속.
- ALIO `jidtDptm`은 기관 내부 부서가 아니라 **주무부처** 코드다. 검수 화면은 주무부처로 표시한다.
- 개정 알림 화면은 이번 범위 밖(메뉴에 "준비 중").
