#!/usr/bin/env bash
# scripts/airflow-metadata-db.sh — 공유 PostgreSQL(21055)에 Airflow 메타 DB reg_airflow를 만든다 (멱등).
# 슈퍼유저 접근은 docker exec psql로 한다. 사용: bash scripts/airflow-metadata-db.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PG_CONTAINER="${PG_CONTAINER:-nais-postgres-1}"
PG_SUPERUSER="${PG_SUPERUSER:-nais}"
if [ -z "${REG_AIRFLOW_DB_PASSWORD:-}" ] && [ -f .env ]; then
  set -a; . ./.env; set +a
fi
: "${REG_AIRFLOW_DB_PASSWORD:?.env에 REG_AIRFLOW_DB_PASSWORD를 넣으세요 (영숫자만: 접속 URL에 그대로 들어감)}"
docker exec -i "$PG_CONTAINER" psql -v ON_ERROR_STOP=1 -q -U "$PG_SUPERUSER" -d postgres \
  -v pw="$REG_AIRFLOW_DB_PASSWORD" < infra/airflow/metadata-db.sql
echo "reg_airflow 준비됨 (${PG_CONTAINER})"
