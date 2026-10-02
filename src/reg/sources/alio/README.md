# sources/alio — ALIO 내부규정 수집 모듈

공공기관 경영정보 공개시스템(ALIO, www.alio.go.kr)의 "내부규정" 공시에서 NST·출연연 규정 파일을 받는다.
소유 테이블: `regulation.institution`(설정 반영), `regulation.alio_rule`, `regulation.alio_rule_file` · 마이그레이션 이력: `migrations/` (version table `regulation.alembic_version_alio`)

## 기관 설정 (`config/sources/alio.yaml`)

- 한 줄 = 기관 하나: `code`, `name`(정식명), `kind`(NST·GRI), `alio_apba_id`, `alio_name`(ALIO 검색어), `active`(없으면 true), `aliases`(약칭).
- `load_institutions`가 `regulation.institution`에 그대로 반영한다(`aliases` → `institution.aliases`).
- 질의응답(`reg.qa.institutions.load_aliases`)은 활성 기관의 정식명·약칭·코드를 DB에서 읽어 질문 속 기관을 알아본다. 약칭을 고치면 다음 수집부터 반영된다.
- 수집한 파일의 `source_document.source_meta`에는 `institution_code`와 수집 시점의 `institution_name`이 함께 남는다.

## 엔드포인트 (2026-10-01 확인, 인증 없음)

| 용도 | 호출 | 쓰는 응답 필드 |
|---|---|---|
| 목록 | `GET /occasional/findRuleList.json?type=apbaNa&word=<기관명>&pageNo=<n>` | `status`, `data.page.totalPage`, `data.result[].{seq, title, apbaId, insdRuleDivis, submissionNo, ruleStDa, idate, crctYn, reSbmtYn}` |
| 상세 | `GET /occasional/findRuleDtl.json?seq=<seq>` | `status`, `data.{title, insdRuleDivis, retryRvsnYmd(개정일), idate(게시일), bFiles}` |
| 파일 | `GET /download/rulefiledown.json?fileNo=<fileNo>` | 본문 바이트 (Content-Type 믿지 않음, 내용으로 형식 판별) |

- 응답 봉투: `{"status": "success", "message": null, "data": {...}}`. 점검 중에는 HTML이나 `status≠success`가 온다(`AlioError`).
- 목록은 한 쪽 10건 고정이고 `word`는 **부분 일치**다. 다른 기관 행이 섞일 수 있어 `apbaId`로 거른다.
- 날짜는 `2024.01.17` 형식 문자열이다.
- 요청 간격 1.5초(`REG_ALIO_MIN_INTERVAL`), 403·3xx·5xx면 즉시 중지(`StopCollecting`), 429/503은 Retry-After를 따른다.

응답 예시: `tests/sources/alio/fixtures/canary_list_kasi_p1.json`, `canary_detail_47852.json` (기록: `uv run python scripts/record_alio_fixtures.py`)

## 변경 판정 (목록 지문)

- 지문 = 목록 행의 `submissionNo|ruleStDa|idate|crctYn|reSbmtYn` (`client.FINGERPRINT_KEYS`, 값은 `str()`로 이어 붙임).
- `alio_rule.list_fingerprint`와 같고 받은 파일이 1개 이상이면 상세·파일 요청을 건너뛰고 `last_seen_at`만 갱신한다.
- 다르면 상세를 받아 `bFiles`의 새 `fileNo`만 내려받는다. 같은 내용(sha256)은 `source_document` 한 행으로 합친다.
- 변경 없는 날 기관 하나의 요청 수 = 목록 쪽 수(기관당 7~22쪽).

## 폐지 감지 (spec 3.3)

- 원장: `alio_rule.missing_since`(처음 사라진 날), `abolish_state`(NULL·CANDIDATE·ABOLISHED), `abolished_on`.
- `regulation.work.status`·`abolished_on`과 검수 작업(kind `ABOLISHED`, target `work:{id}`)은 원장에서 만드는 투영(`reconcile.project`).
- 순서
  1. `collect_institution`이 `complete`(상한 없이 목록 끝까지 예외 없이)와 `started_at`(DB `now()`)을 돌려준다.
  2. `reconcile(results)`가 완결된 기관만 `last_seen_at < started_at`인 규정에 `missing_since`를 적는다(이미 있으면 유지). 본 규정은 지운다.
  3. `missing_since <= 오늘-2`(KST, 3일째)이고 규정에 work가 있으면 폐지 후보 → 검수 큐.
  4. 사람이 `reg alio abolish WORK_ID`로 확정(폐지일 = missing_since) 또는 `--reject`로 반려(현행, missing_since 초기화).
  5. 다시 목록에 나타나면 후보·폐지 모두 현행으로 돌아가고 열린 작업은 DISMISSED.
- 목록 급감 보호: 알려진 규정 10건 이상인데 본 규정이 절반 미만이면 그날은 사라짐을 기록하지 않는다(`guard` 메시지).
- `reg process --rebuild` 뒤에는 `reg alio reconcile`로 상태·작업을 되살린다.

## 알려진 특이점

- **`bFiles`에 개정 이력 전체가 들어 있다.** `"151446|…(2022년 5월 제정).pdf,186628|…(2024년도 1월 개정).pdf"`. 파일명에 쉼표가 있을 수 있어 `,(?=\d+\|)`로 나눈다. 마지막(ord 최대) 파일에만 ALIO 개정일(`retryRvsnYmd`)을 시행일 근거로 쓴다(handler).
- **HWP 5.0(OLE) 본문의 확장 한자는 UTF-16 서로게이트 쌍으로 온다.** 쌍을 합쳐 실제 문자로 만든다(`reg.core.extract.hwp`, `surrogatepass`). 파일의 약 절반이 HWP 5.0, 나머지는 텍스트 층이 있는 PDF다.
- **거부 파일 33건 (2026-10-02 실 DB, 통합 단계에서 다시 확인)**: ETRI 32건은 서식·별첨 묶음 `.zip`, NST 1건은 확장자가 `.hwp`인데 내용이 ZIP(PK, HWPX로 추정)이다. 형식 판별(`sniff`)은 PDF·HWP 5.0·이름이 `.hwpx`인 ZIP만 인정하므로 `alio_rule_file.status='rejected'`, `reject_reason='형식 불명 (b'PK…')'`로 남고, 다음 수집 때 다시 시도한다.
- **같은 `fileNo`가 중복된다.** 한 `bFiles` 안에서 두 번 나오거나 다른 규정의 `bFiles`에 다시 나온다. `alio_rule_file`의 키가 `file_no`라 처음 기록한 규정에 붙고 다시 받지 않는다.
- 국가보안기술연구소(NSR)는 ALIO 검색 결과가 0건이다(공시 대상 아님). 설정에 `alio_apba_id: null`, `active: false`로 둔다.

## 응답 구조 점검 (canary)

- 일 배치 첫 태스크(`tasks.active_institutions`)가 `canary.run_canary`를 먼저 돈다: KASI 목록 1쪽 + seq 47852 상세(요청 2회).
- 구조가 다르면 `AlioSchemaChanged("ALIO 응답 구조 변경: findRuleList data.result[0].title 없음")`처럼 위치가 보이는 메시지로 실패하고, 수집은 시작하지 않는다.
- 점검·장애는 `AlioError`(구조 변경 아님, Airflow 재시도).
- 47852가 폐지되면 같은 쪽의 다른 seq로 대신 점검하고 `warning`을 남긴다. 그때 `canary.CANARY_SEQ`를 바꾼다.
- 수동: `reg alio canary` (0 정상, 2 구조 변경, 1 점검·장애)

## 사이트가 바뀌었을 때 점검표

1. `reg alio canary`를 돌려 메시지에 나온 위치(엔드포인트·필드)를 확인한다.
2. `uv run python scripts/record_alio_fixtures.py`로 응답을 다시 기록하고 `git diff tests/sources/alio/fixtures`로 바뀐 필드를 본다.
3. 필드명·형식이 바뀌었으면 `client.py`(목록·상세 파싱, `FINGERPRINT_KEYS`)와 `canary.py`(점검 목록)를 함께 고친다.
4. 지문 필드가 바뀌면 다음 수집에서 모든 규정의 상세를 다시 받는다(규정 수만큼 요청, 기관당 수 분). 일정에 반영한다.
5. 파일 다운로드가 바뀌면 `sync.py`의 `DOWNLOAD_URL`과 `client.download`를 고치고, 받은 바이트의 앞부분으로 `sniff`가 형식을 알아보는지 확인한다.
6. 기관명이 바뀌면 목록이 0건이 된다(급감 보호가 막는다). `config/sources/alio.yaml`의 `alio_name`을 고친다.
7. `uv run pytest tests/sources/alio -q`가 통과하면 커밋하고, 다음 일 배치에서 `reg alio canary`가 0으로 끝나는지 본다.

## 기관 추가 (backfill)

1. `config/sources/alio.yaml`에서 기관 줄을 찾는다(NST 소관 25곳은 모두 있다). 없으면 한 줄을 추가한다:
   `- {code: XXX, name: 기관명, kind: GRI, alio_apba_id: C0000, alio_name: 기관명, active: false}`
   - apbaId 확인: `findRuleList.json?type=apbaNa&word=기관명&pageNo=1`에서 `pname`이 기관명과 정확히 같은 행의 `apbaId`.
2. `reg alio backfill --institution XXX` — 응답 구조 점검 → 비활성이어도 전체 수집 → 대조.
3. `reg process --all` — 받은 파일을 파싱·적재한다. 결과는 `/regulations?inst=XXX`와 검수 큐에서 본다.
4. 문제가 없으면 `active: true`로 바꾼다. 다음 일 배치(`reg_alio_daily`)부터 포함된다.
