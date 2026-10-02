# Airflow 일 배치 런북

- 대상: 운영자. 배치 설계는 `docs/superpowers/specs/2026-10-02-batch-pipeline-design.md` §1·§2·§9.
- UI: `http://192.168.0.3:21062` (관리자: `.env`의 `REG_AIRFLOW_ADMIN_USER` / `REG_AIRFLOW_ADMIN_PASSWORD`)
- 모든 명령은 저장소 루트에서 실행한다. compose는 항상 `scripts/airflow.sh`를 거친다.
- **`docker compose down`을 직접 쓰지 않는다.** 원본 보관소(storage)와 neo4j까지 내려간다.

## 구성

| 서비스 | 하는 일 |
|---|---|
| `airflow-apiserver` | UI·API (21062) |
| `airflow-scheduler` | 일정 판단 + 태스크 실행 (LocalExecutor) |
| `airflow-dag-processor` | `airflow/dags/` 파싱 |
| `airflow-init` | 메타 DB 마이그레이션, 관리자 계정, Pool(`alio_pool`=2, `lawgo_pool`=1, `gpu_pool`=1). 실행 후 종료 |
| `converter` | HWP→PDF 변환 (내부 전용) |

- GPU PC 주소(`REG_EMBED_URL`·`REG_RERANK_URL`·`REG_LLM_URL`, OCR의 `REG_MINERU_URL`·`REG_MINERU_API_KEY` = MinerU `http://192.168.0.2:8004`)는 `.env` 값을 그대로 받는다(env_file). 컨테이너에 docker 소켓은 주지 않는다.
- 메타 DB는 공유 PostgreSQL(21055)의 `reg_airflow`다. 배치 결과는 `nst_regulation`의 `ops.pipeline_run`에 남는다.
- 실패 알림 메일은 아직 없다(D-6). 실패는 두 곳에서 본다.
  - Airflow UI의 빨간 태스크
  - `ops.pipeline_run`의 `stats->>'source' = 'on_failure_callback'` 행

## 일정 (KST)

| DAG | 일정 | 하는 일 |
|---|---|---|
| `reg_law_daily` | 매일 01:00 | 법령 변경분 미러링 → 파싱(`reg_process`) |
| `reg_law_full` | 일요일 00:00 + 수동 | 법령 전체 대조 (최초 적재는 수동) |
| `reg_law_link` | 파싱 직후 (Asset) | 내부규정 법령 인용 연계 → 인용 법령 승격 → 승격 건이 있으면 다시 파싱 |
| `reg_alio_daily` | 매일 02:00 | ALIO 기관별 수집 → 폐지 대조 |
| `reg_process` | 수집·승격·OCR 직후 (Asset) + 03:30 안전망 | 파싱·적재·품질 집계 |
| `reg_ocr` | 파싱 직후 (Asset) | LOW_TEXT OCR → 처리 건이 있으면 다시 파싱 |
| `reg_publish` | 파싱 직후 (Asset) | 그래프·영향 분석 / 임베딩 확인·색인·게이트·게시 → 하루 요약 |
| `reg_notify` | 매시 05분 | 알림 메일 |
| `reg_maintenance` | 매일 04:00 | 로그 정리(요청 90일·질의 365일·Airflow 30일), 옛 색인 삭제 |
| `reg_backfill` | 수동 | 신규 기관 전체 수집 |

법령은 M6-1 순서 계약대로 돈다: `sync_daily` → `reg_process` → `reg_law_link`(link → promote) → (승격 건이 있으면) `reg_process`.

새 DAG는 **일시정지 상태로** 올라온다. UI에서 토글을 켜야 돈다.

## 처음 설치 (1회)

1. `.env`에 `.env.example`의 `# --- Airflow` 아래 키를 채운다. 키 만드는 명령은 예시 파일의 주석에 있다.
2. `bash scripts/airflow.sh init-db` — `reg_airflow` 역할·DB 생성 (여러 번 실행해도 안전)
3. `bash scripts/airflow.sh build` — 이미지 `nst-regulation/airflow:3.3.2`, `nst-regulation/converter:0.2`
4. `bash scripts/airflow.sh check` — DAG 점검 (`DAG 점검 통과: 10개`)
5. `bash scripts/airflow.sh up` → `bash scripts/airflow.sh ps`로 healthy 확인 → UI 로그인

## 시작·중지·상태

```bash
bash scripts/airflow.sh up        # 시작 (init이 먼저 돌고 끝난 뒤 나머지가 뜬다)
bash scripts/airflow.sh down      # Airflow·변환기만 멈춤 (storage·neo4j는 그대로)
bash scripts/airflow.sh ps        # 상태
bash scripts/airflow.sh logs                      # 스케줄러 로그 (태스크 실행도 여기)
bash scripts/airflow.sh logs airflow-apiserver    # 다른 서비스
```

Airflow가 내려가 있어도 CLI로 같은 일을 할 수 있다.
- 수집: `uv run reg alio collect`
- 파싱: `uv run reg process --all`
- 색인: `uv run reg index build`
- 요약: `uv run reg ops summary`

## 코드·설정을 바꾼 뒤

| 바뀐 것 | 할 일 |
|---|---|
| `src/reg/**` (배치 코드) | `bash scripts/airflow.sh build && bash scripts/airflow.sh up` (바뀐 컨테이너만 다시 만든다) |
| `airflow/dags/**` | 할 일 없음. 마운트되어 있어 1분 안에 다시 읽는다 |
| `config/**` (기관 목록 등) | 할 일 없음. 마운트되어 있다 |
| `.env` | `bash scripts/airflow.sh up` (환경이 바뀐 컨테이너를 다시 만든다) |

## UI 로그인·비밀번호 변경

- 주소 `http://192.168.0.3:21062`, 계정은 `.env`의 관리자 값이다.
- 비밀번호 변경
  1. `.env`의 `REG_AIRFLOW_ADMIN_PASSWORD`를 바꾼다.
  2. 다음을 실행한다.

     ```bash
     docker compose --env-file .env -f infra/docker-compose.yml exec airflow-apiserver airflow users delete -u "$REG_AIRFLOW_ADMIN_USER"
     bash scripts/airflow.sh up      # airflow-init이 새 비밀번호로 다시 만든다
     ```

## 실패한 태스크 다시 실행

모든 태스크는 멱등이다. 같은 태스크를 다시 돌려도 중복 적재가 없다.

1. UI → DAG → 실패한 실행(빨간 칸) → 실패한 태스크 → **Clear**.
2. 뒤 태스크도 다시 돌리려면 "Downstream"을 켠다.
3. CLI로 할 때:

```bash
docker compose --env-file .env -f infra/docker-compose.yml exec airflow-scheduler \
  airflow tasks clear reg_alio_daily --task-regex '^collect$' --start-date 2026-10-02 --end-date 2026-10-03 --downstream --yes
```

최근 최종 실패 목록:

```sql
SELECT started_at, dag_id, task_id, run_id, left(error, 200) AS error
  FROM ops.pipeline_run WHERE stats->>'source' = 'on_failure_callback' ORDER BY id DESC LIMIT 20;
```

하루 요약:

```sql
SELECT stats FROM ops.pipeline_run WHERE dag_id = 'reg_summary' ORDER BY run_id DESC LIMIT 1;
```

## 신규 기관 백필

1. `config/`의 기관 목록에 한 줄을 추가한다(마운트되어 있어 재시작 불필요).
2. UI → `reg_backfill` → **Trigger** → conf에 `{"institutions": ["KAERI"]}`를 넣는다. CLI로는 다음과 같다.

   ```bash
   docker compose --env-file .env -f infra/docker-compose.yml exec airflow-scheduler \
     airflow dags trigger reg_backfill --conf '{"institutions": ["KAERI"]}'
   ```

3. 활성 목록에 없는 코드면 `targets` 태스크가 "활성 기관이 아님"으로 실패한다(설정 확인).
4. 수집이 끝나면 파싱(`reg_process`)과 게시(`reg_publish`)가 자동으로 이어진다. 다음 날부터는 `reg_alio_daily`에 포함된다.

## 파서를 바꾼 뒤 전체 재파싱

Airflow 진입점이 없다(계약 표 밖). CLI로 한다. 재처리 중에도 검색은 이전 release로 동작한다.

```bash
uv run reg process --rebuild
```

끝나면 UI에서 `reg_publish`를 수동 Trigger한다.

## GPU PC(192.168.0.2)가 꺼져 있을 때

- 색인만 미뤄진다.
  - `reg_publish.embed_check`가 30분 간격으로 6회(약 3시간) 다시 확인한다.
  - 그동안 그래프·영향 분석·하루 요약은 진행된다.
  - 검색·질의응답은 이전 release로 계속 동작한다.
- 6회가 모두 실패하면 `embed_check`가 빨갛게 남는다.
- GPU를 켠 뒤 확인하고 다시 돌린다.
  1. 컨테이너에서 닿는지 확인한다.

     ```bash
     docker compose --env-file .env -f infra/docker-compose.yml exec airflow-scheduler \
       python -c "import httpx; print(httpx.get('http://192.168.0.2:8002/v1/models', timeout=5).status_code)"
     ```

  2. `200`이면 UI에서 그 실행의 `embed_check`를 **Clear**(Downstream 켬)하거나, `reg_publish`를 새로 Trigger한다.
- 컨테이너는 호스트(192.168.0.3)의 NAT로 나간다. 그래서 호스트에서 `bash infra/vllm-local/check.sh 192.168.0.2`가 되는데 컨테이너에서 안 되면 Docker 네트워크 대역을 의심한다.
  - 정상 대역은 172.x다. `docker network inspect nst-regulation_default`로 확인한다.
  - 새 네트워크가 192.168.x를 받으면 LAN을 가린다.

## 변환기 문제

- 증상: 보기용 PDF가 안 생긴다(`source_document.view_status = 'failed'`). 조문 파싱은 계속된다.
- 확인

  ```bash
  bash scripts/airflow.sh logs converter
  docker compose --env-file .env -f infra/docker-compose.yml exec airflow-scheduler \
    python -c "import httpx; print(httpx.get('http://converter:8080/healthz').text)"
  ```

- 호스트 CLI(`uv run reg process`)는 compose 변환기 대신 `docker run nst-regulation/converter:0.2`를 쓴다(`REG_CONVERTER_URL` 미설정).

## 로그·보관

- 태스크 로그는 볼륨 `nst-regulation_airflow-logs`에 쌓인다. `reg_maintenance`가 30일 지난 파일을 지운다.
- `ops.request_log` 90일, `ops.qa_log` 365일, 옛 release 색인(게시본+직전 1개 남김)은 `reg_maintenance`가 정리한다.
