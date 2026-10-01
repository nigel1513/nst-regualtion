#!/usr/bin/env bash
# 기동 + healthy 대기 + 동작 확인. 사용법: cd ~/vllm && bash up.sh
set -u
cd "$(dirname "$0")"
docker compose up -d || exit 1

echo "기동 대기 중 (첫 실행은 이미지·모델 다운로드로 10~20분)…"
deadline=$(( $(date +%s) + 2400 ))
while :; do
  st=$(docker compose ps --format '{{.Service}}={{.Health}}' | sort | tr '\n' ' ')
  printf '\r  %s ' "$st"
  case "$st" in *unhealthy*) echo; echo "unhealthy 발생:"; docker compose logs --tail 40; exit 1;; esac
  [ "$(docker compose ps --format '{{.Health}}' | grep -c '^healthy$')" = 3 ] && break
  if [ "$(date +%s)" -gt "$deadline" ]; then echo; echo "40분 초과"; docker compose logs --tail 40; exit 1; fi
  sleep 10
done
echo; echo "세 서비스 모두 healthy"; nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader
echo
bash ./check.sh
