#!/usr/bin/env bash
# infra/airflow/init.sh — airflow-init 서비스: 메타 DB 마이그레이션 → 관리자 계정 → Pool. 여러 번 실행해도 같다.
set -euo pipefail
: "${REG_AIRFLOW_ADMIN_USER:?.env에 REG_AIRFLOW_ADMIN_USER를 넣으세요}"
: "${REG_AIRFLOW_ADMIN_PASSWORD:?.env에 REG_AIRFLOW_ADMIN_PASSWORD를 넣으세요}"

airflow db migrate
if airflow fab-db --help >/dev/null 2>&1; then
  airflow fab-db migrate
fi

if airflow users list -o json 2>/dev/null | python -c '
import json, os, sys
users = json.load(sys.stdin)
sys.exit(0 if any(u.get("username") == os.environ["REG_AIRFLOW_ADMIN_USER"] for u in users) else 1)'; then
  echo "관리자 계정 있음: ${REG_AIRFLOW_ADMIN_USER} (비밀번호 변경은 docs/ops/airflow.md)"
else
  airflow users create --role Admin --username "${REG_AIRFLOW_ADMIN_USER}" \
    --password "${REG_AIRFLOW_ADMIN_PASSWORD}" --firstname NST --lastname Admin \
    --email "admin@nst-regulation.local"
fi

airflow pools set alio_pool 2 "ALIO 서버 예의: 기관 2곳까지 동시 수집"
airflow pools set lawgo_pool 1 "law.go.kr 요청은 한 줄로"
airflow pools set gpu_pool 1 "GPU(192.168.0.2) 임베딩·평가가 겹치지 않게"
