#!/usr/bin/env bash
# 기동 + healthy 대기 + 확인. 사용법: cd ~/gpu-mineru && bash up.sh
set -u
cd "$(dirname "$0")"
[ -f .env ] || { echo "MINERU_API_KEY=$(openssl rand -hex 16)" > .env; echo ".env 생성 (API 키): $(cat .env)"; }
docker compose up -d || exit 1
echo "기동 대기 중…"
deadline=$(( $(date +%s) + 1800 ))
until [ "$(docker compose ps --format '{{.Health}}' | grep -c '^healthy$')" = 2 ]; do
  case "$(docker compose ps --format '{{.Health}}')" in *unhealthy*) docker compose logs --tail 40; exit 1;; esac
  [ "$(date +%s)" -gt "$deadline" ] && { echo "30분 초과"; docker compose logs --tail 40; exit 1; }
  sleep 10
done
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader
bash ./check.sh
echo; echo "플랫폼 서버에 알려줄 값 → REG_MINERU_URL=http://192.168.0.2:8004  REG_MINERU_API_KEY=$(cut -d= -f2 .env)"
