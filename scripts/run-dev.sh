#!/usr/bin/env bash
# API(:21061)와 웹(:21060)을 백그라운드로 띄운다. PID: .run/*.pid, 로그: .run/*.log
# 순서: 빌드 → (성공 시) 기존 프로세스 종료 → 포트 해제 대기 → 기동 → 상태 확인
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
mkdir -p "$ROOT/.run"
set -a; . ./.env; set +a

if ! (cd "$ROOT/apps/web" && npm run build > "$ROOT/.run/web-build.log" 2>&1); then
  echo "웹 빌드 실패 — 기존 서비스는 그대로 둡니다" >&2; tail -20 "$ROOT/.run/web-build.log" >&2; exit 1
fi

stop() {  # $1=이름 $2=명령줄에 있어야 하는 문자열 (PID 재사용으로 엉뚱한 프로세스를 죽이지 않게)
  local f="$ROOT/.run/$1.pid"
  [ -f "$f" ] || return 0
  local pid; pid="$(cat "$f")"
  if kill -0 "$pid" 2>/dev/null && tr '\0' ' ' < "/proc/$pid/cmdline" | grep -q -- "$2"; then
    kill -- "-$pid" 2>/dev/null || kill "$pid" || true
  fi
  rm -f "$f"
}
stop api "reg api"
stop web "next"
for port in 21061 21060; do
  for _ in $(seq 1 30); do ss -ltn "( sport = :$port )" | grep -q LISTEN || break; sleep 1; done
done

setsid uv run reg api --host 0.0.0.0 --port 21061 > "$ROOT/.run/api.log" 2>&1 < /dev/null & echo $! > "$ROOT/.run/api.pid"
(cd "$ROOT/apps/web" && exec setsid npm run start > "$ROOT/.run/web.log" 2>&1 < /dev/null) & echo $! > "$ROOT/.run/web.pid"

for _ in $(seq 1 60); do
  if curl -sf localhost:21061/api/v1/institutions >/dev/null && curl -sf -o /dev/null localhost:21060/regulations; then
    echo "API  http://$(hostname -I | awk '{print $1}'):21061/docs"
    echo "WEB  http://$(hostname -I | awk '{print $1}'):21060/regulations"
    exit 0
  fi
  sleep 2
done
echo "서비스가 응답하지 않습니다" >&2; tail -10 "$ROOT/.run/api.log" "$ROOT/.run/web.log" >&2; exit 1
