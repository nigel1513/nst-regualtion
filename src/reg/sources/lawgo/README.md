# sources/lawgo — law.go.kr 법령 미러

현행 법령 전체와 NST 산하에 필요한 행정규칙을 `law` 스키마(전용 DB `nst_regulation`)에 미러링한다.
내부규정 인용을 조문 외래키로 잇고, 인용된 것만 `regulation.work`로 승격한다.
설계: `docs/superpowers/specs/2026-10-02-batch-pipeline-design.md` §3A · 계획: `docs/superpowers/plans/2026-10-02-m6-1-lawgo.md`

## 파일

| 파일 | 하는 일 |
|---|---|
| `client.py` | DRF 호출만. 본문으로 오류 판별(`errors.py`), 요청 로그의 OC 가림 |
| `xml.py` | 목록(`parse_list`)·법령 본문(`parse_law_xml`)·행정규칙 본문(`parse_admrul_xml`) 해석 |
| `mirror.py` | `law` 스키마 쓰기 (이 모듈 밖에서 `law`에 쓰지 않는다) |
| `sync.py` | 일 변경분·주간 전체 대조·별표 본문·canary·status |
| `select.py` | 행정규칙 선별 (인용 이름 + 설정) |
| `link.py` | `regulation.reference.target_law_id / target_law_article_id` |
| `promote.py` · `handler.py` | 승격(outbox `regulation.law_fetched`) · 처리기(`PreparedVersion`) |
| `api.py` | 다른 모듈·API용 읽기 함수 |
| `urls.py` · `ids.py` | law.go.kr 링크(형식이 바뀌면 여기만) · 식별자 규칙 |
| `tasks.py` · `cli.py` | Airflow·CLI 진입점 |

## 호출하는 엔드포인트

키: `OC={REG_LAWGO_OC}`(요청 때만 붙인다. 저장·로그에는 `OC=***`). 요청 간격 1초 이상. User-Agent는 `NST-Regulation-Collector`.

| 용도 | 요청 | 비고 |
|---|---|---|
| 법령 목록 (최신순) | `GET /DRF/lawSearch.do?target=law&type=XML&sort=ddes&page=&display=100` | 행 `<law>`: 법령일련번호(MST), 법령ID, 법령명한글, 법령약칭명, 공포일자, 공포번호, 제개정구분명, 소관부처명, 법령구분명, 시행일자, 현행연혁코드 |
| 행정규칙 목록 (최신순) | `…target=admrul&sort=ddes` | 행 `<admrul>`: 행정규칙일련번호, 행정규칙ID, 행정규칙명, 행정규칙종류, 발령일자, 발령번호, 현행연혁구분 |
| 법령 별표 목록 | `…target=licbyl&search=2&query={법령명}` | `search=2` = 관련 법령명(포함 검색) → `관련법령ID`로 거른다. `search=3`은 별표 본문 검색이라 쓰지 않는다 |
| 행정규칙 별표 목록 | `…target=admbyl&search=2&query={행정규칙명}` | 행 `<admrulbyl>`. PDF 링크 없음 |
| 법령 본문 | `GET /DRF/lawService.do?target=law&MST={mst}&type=XML` | `<기본정보>`, `<조문단위>`(항·호·목 태그), `<부칙단위>` |
| 행정규칙 본문 | `…target=admrul&ID={행정규칙일련번호}&type=XML` | `<행정규칙기본정보>`, `<조문내용>`(조 전체가 문자열), `<부칙>` |
| 별표 본문 | `…target=licbyl|admbyl&ID={별표일련번호}&type=HTML` | 3KB 껍데기: law.go.kr 뷰어 iframe. 원본 그대로 저장 |
| 별표 PDF | `GET /LSW/flDownload.do?flSeq=…` (목록의 `별표서식PDF파일링크`) | OC 불필요. licbyl만 |

규모(2026-10-02): law 5,627 · admrul 24,162 · licbyl 39,787 · admbyl 84,341.

## 저장

- `law.law_master` / `law_version`(법령당 현행 1개, 지난 판본은 판본 정보만) / `article`(현행 조문, id 유지) / `annex` / `admrul_catalog` / `sync_run` / `change_log`
- 본문 XML: SeaweedFS `raw/lawgo/…`(`regulation.source_document`, `source='lawgo'`)
- 별표: `law/annex/{별표일련번호}.html`(원본), `.pdf`
- `law.alembic_version` 이력: `sources/lawgo/migrations`

## 실행 순서

1. 최초: `reg law full` (법령 5,627건 본문 ≈ 1시간 40분 + licbyl 목록 398쪽 + 행정규칙 카탈로그 242쪽)
2. 별표 본문 밀린 것: `reg law annex --limit 2000` (실행당 상한, `annex.body_limit_per_run`)
3. 매일 01:00: `sync_daily` → `reg_process` 뒤 `link` → `promote` → `reg_process`
4. 매주: `sync_full`

## 알려진 특이점

- 오류도 HTTP 200으로 온다. 판별은 `client.check`가 한다.
  - `<h2>미신청된 목록/본문에 대한 접근입니다.</h2>`(HTML) → `KeyNotApproved`. 키는 있으나 그 API·법령종류가 승인되지 않은 상태다.
  - `<Response><result>사용자 정보 검증에 실패하였습니다.</result>` → `KeyRejected`. 키 미등록이거나 서버 IP가 등록 IP(116.43.250.15)와 다르다.
  - `<Response><result>필수입력요소 검증에 실패하였습니다.</result>` → `KeyRejected`. OC가 빠졌다.
  - `<Law>일치하는 법령이 없습니다.</Law>`, `<Law>일치하는 행정규칙이 없습니다.</Law>` → `NotFound`
- `sort=ddes`는 law·admrul만 된다. 별표 목록은 정렬되지 않으므로 바뀐 법령 기준으로 받는다.
- admrul 최신순 목록에 `현행연혁구분=연혁` 행이 섞인다. 현행 행만 쓴다. 늦게 현행이 된 판본은 주간 전체 대조가 잡는다.
- 목록 끝을 넘긴 쪽은 `numOfRows=0`이고 행이 없다.
- 공포번호는 앞에 0이 붙어 올 수 있다(`03277`). 화면의 판본 줄에서는 뗀다.
- law.go.kr 화면 링크는 없는 이름에도 200을 준다(`<title>…오류페이지</title>`).
- DRF 별표 HTML은 내용이 없는 껍데기다. 바로 보기는 PDF를 먼저 쓴다.

## 사이트가 바뀌었을 때 점검표

1. `reg law status --canary`의 오류 메시지를 본다. 어느 목록·태그가 없는지 나온다.
2. `tests/sources/lawgo/fixtures/record.sh`로 표본을 다시 받는다(OC=test). `git diff --stat`으로 바뀐 파일을 본다.
3. `uv run pytest tests/sources/lawgo -q`를 돌린다.
   - 목록 태그가 바뀌었으면 `xml.LIST_SPEC`과 `_*_row`를 고친다.
   - 본문이 바뀌었으면 `parse_law_xml`·`parse_admrul_xml`을 고친다.
   - 합성 XML(`tests/sources/lawgo/helpers.py`)도 같이 고친다.
4. 오류 안내 문구가 바뀌었으면 `client.check`와 `fixtures/unapproved.html`을 고친다.
5. 링크 형식이 바뀌었으면 `urls.py`만 고치고, 계획서 Task 4 Step 5의 curl 점검을 다시 돌린다.
6. 파라미터가 바뀌었으면(`sort`, `search`, `display` 상한) `client.py`와 이 표를 고친다.
7. 고친 뒤 `reg law sync --date {마지막 정상일}`로 그 사이 변경분을 다시 훑는다.

## canary

`sync.canary(client)`는 일·전체 동기화의 첫 단계다. `reg law status --canary`로 따로도 돌린다. 최소 요청 3개를 보낸다.

1. `lawSearch target=law display=1 sort=ddes`: `<LawSearch>`, `<totalCnt>` ≥ 1000, 행의 필수 태그 5개
2. 1의 MST로 `lawService target=law`: `<기본정보>`와 조문 1개 이상
3. `lawSearch target=admrul display=1 sort=ddes`: `<totalCnt>` ≥ 1000

하나라도 어긋나면 `ResponseChanged("law 목록 응답 구조 변경: <law>에 <법령일련번호> 없음")`처럼 원인이 보이는 메시지로 실패한다. 그 경우 수집은 시작하지 않는다.

## 판정 요약 (계획서 R1~R16)

- FK 열은 이 모듈 이력이 더한다.
- 조문 id는 판본을 넘어 유지한다. 인용 중인 삭제 조문은 `gone_in_mst`로 남긴다.
- 별표는 `search=2` + ID로 거른다. HTML 원본과 함께 PDF도 저장한다(사용자 확인 대기).
- 전체 대조는 목록이 95% 미만이면 폐지 처리 없이 실패한다.
- 무매칭 이름은 core `REFERENCE` 검수가 맡는다.
- `kr/admrul/…` work는 core 제목 매칭 밖이다(통합 때 처리).
