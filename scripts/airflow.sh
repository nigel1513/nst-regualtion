#!/usr/bin/env bash
# scripts/airflow.sh — Airflow·변환기 compose 래퍼 (저장소 루트의 .env를 씀).
# 사용: scripts/airflow.sh build|up|down|ps|logs [서비스…]|init-db|check
# down은 Airflow·변환기만 멈춘다. 프로젝트 전체 `docker compose down`은 storage·neo4j까지 내리므로 쓰지 않는다.
set -euo pipefail
cd "$(dirname "$0")/.."
DC=(docker compose --env-file .env -f infra/docker-compose.yml)
RUN_SVCS=(converter airflow-apiserver airflow-scheduler airflow-dag-processor)
case "${1:-}" in
  build)   "${DC[@]}" build converter airflow-init ;;
  up)      "${DC[@]}" up -d airflow-init "${RUN_SVCS[@]}" ;;
  down)    "${DC[@]}" stop "${RUN_SVCS[@]}" ;;
  ps)      "${DC[@]}" ps converter airflow-init "${RUN_SVCS[@]}" ;;
  logs)    shift; if [ $# -eq 0 ]; then set -- airflow-scheduler; fi; "${DC[@]}" logs -f --tail=200 "$@" ;;
  init-db) bash scripts/airflow-metadata-db.sh ;;
  check)   bash scripts/airflow-check.sh ;;
  *) echo "사용법: $0 build|up|down|ps|logs [서비스…]|init-db|check" >&2; exit 2 ;;
esac
