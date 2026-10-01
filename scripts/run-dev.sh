#!/usr/bin/env bash
# API(:21061)와 웹(:21060)을 백그라운드로 띄운다. PID: .run/*.pid, 로그: .run/*.log
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
mkdir -p "$ROOT/.run"
set -a; . ./.env; set +a
for name in api web; do
  if [ -f ".run/$name.pid" ] && kill -0 "$(cat .run/$name.pid)" 2>/dev/null; then
    kill -- -"$(ps -o pgid= "$(cat .run/$name.pid)" | tr -d ' ')" 2>/dev/null || kill "$(cat .run/$name.pid)" || true
  fi
done
(cd "$ROOT/apps/web" && npm run build > "$ROOT/.run/web-build.log" 2>&1)
setsid nohup uv run reg api --host 0.0.0.0 --port 21061 > .run/api.log 2>&1 < /dev/null & echo $! > .run/api.pid
cd "$ROOT/apps/web"
setsid nohup npm run start > "$ROOT/.run/web.log" 2>&1 < /dev/null & echo $! > "$ROOT/.run/web.pid"
cd "$ROOT"
for _ in $(seq 1 60); do
  curl -sf localhost:21061/api/v1/institutions >/dev/null && curl -sf -o /dev/null localhost:21060/regulations && break
  sleep 2
done
echo "API  http://$(hostname -I | awk '{print $1}'):21061/docs"
echo "WEB  http://$(hostname -I | awk '{print $1}'):21060/regulations"
