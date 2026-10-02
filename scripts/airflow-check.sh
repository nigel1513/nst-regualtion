#!/usr/bin/env bash
# scripts/airflow-check.sh — Airflow 이미지 안에서 DAG를 점검한다 (주 venv에 airflow를 넣지 않는다).
# compose 서비스를 띄우지 않는다: 일회용 컨테이너, 네트워크 없음. 사용: bash scripts/airflow-check.sh [SKIP_BUILD=1]
set -euo pipefail
cd "$(dirname "$0")/.."
IMAGE="${AIRFLOW_IMAGE:-nst-regulation/airflow:3.3.2}"
if [ "${SKIP_BUILD:-0}" != "1" ]; then
  docker build -q -f infra/airflow/Dockerfile -t "$IMAGE" . >/dev/null
fi
docker run --rm --network none \
  -e AIRFLOW__CORE__LOAD_EXAMPLES=false \
  -e AIRFLOW__CORE__DAGS_FOLDER=/opt/airflow/dags \
  -e AIRFLOW__CORE__DEFAULT_TIMEZONE=Asia/Seoul \
  -v "$PWD/airflow/dags:/opt/airflow/dags:ro" \
  -v "$PWD/airflow/tests:/opt/airflow/checks:ro" \
  --entrypoint python "$IMAGE" /opt/airflow/checks/check_dags.py
