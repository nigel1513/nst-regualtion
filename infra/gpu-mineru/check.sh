#!/usr/bin/env bash
# MinerU API 확인. 사용법: bash check.sh [host]
H=${1:-localhost}
KEY=$(cut -d= -f2 "$(dirname "$0")/.env" 2>/dev/null)
echo "== health";  curl -s --max-time 10 "http://$H:8004/v1/health" | head -c 400; echo
echo "== tiers";   curl -s --max-time 10 -H "Authorization: Bearer $KEY" "http://$H:8004/v1/tiers" | head -c 400; echo
