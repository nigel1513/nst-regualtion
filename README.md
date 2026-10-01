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
