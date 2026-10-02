# nst-regulation

NST와 출연연의 내부규정, 관련 법령을 다루는 인텔리전스 플랫폼입니다. 주요 기능은 다음과 같습니다.

- 수집, 구조화, 버전 관리
- 규정 뷰어
- 근거 기반 질의응답
- 개정 영향 알림

## 문서

- [PRD](docs/PRD.md)
- [설계 스펙](docs/superpowers/specs/2026-10-01-regulation-platform-design.md)

## 구성

| 경로 | 내용 |
|---|---|
| `infra/vllm-local/` | 개발용 추론 서버 (Windows WSL2, RTX 4090). EXAONE-3.5-7.8B-AWQ, bge-m3, bge-reranker-v2-m3 |

`infra/vllm-local/`은 다음 순서로 사용합니다.

1. `bash up.sh`로 서버를 띄웁니다.
2. `bash check.sh [host]`로 점검합니다.

## 포트

이 프로젝트의 서비스는 21060~21069번 포트를 씁니다. 공유 인프라의 엔드포인트는 설계 스펙 4.1절을 참고하세요.

## 실행 (M1 수집)

```bash
cp .env.example .env                 # 비밀번호·키 채우기 (REG_SUPERUSER_URL = 공유 Postgres 슈퍼유저)
infra/storage/gen-s3-config.sh       # .env의 S3 키로 전용 SeaweedFS 인증 설정 생성
docker compose -f infra/docker-compose.yml up -d   # 원본 보관소 (127.0.0.1:21066)
set -a; . ./.env; set +a
uv run reg db bootstrap              # 역할 reg_migrator/reg_app, 스키마 regulation 생성 (멱등)
uv run reg db upgrade                # 마이그레이션
uv run reg bucket ensure             # 버킷 생성
uv run reg collect law               # 핵심 법령 (config/laws.yaml) — 바뀐 것만 받음
uv run reg collect alio [--institution KASI] [--limit N]   # ALIO 내부규정 (config/institutions.yaml)
```

테스트: `uv run pytest` (Docker 필요, testcontainers), 실인프라 테스트: `uv run pytest -m integration`

## 화면 실행 (M3)

```bash
bash scripts/run-dev.sh        # API :21061, 웹 :21060 (빌드 포함), PID·로그는 .run/
```

- 웹: `http://<서버>:21060/regulations` — 규정 목록·조문 뷰어·원문 대조·신구 비교·검색·검수 큐
- API 문서: `http://<서버>:21061/docs`
- 처리 작업자 병렬 실행: `uv run reg process --all` 를 여러 개 띄워도 된다 (규정 단위 잠금)
