#!/usr/bin/env bash
# 세 서비스 동작 확인. 사용법: bash check.sh [host]   (기본 localhost, 포트 8001/8002/8003)
# 서버에서 터널 확인 시: LLM_PORT=21061 EMB_PORT=21062 RR_PORT=21063 bash check.sh
H=${1:-localhost}
LLM=${LLM_PORT:-8001}; EMB=${EMB_PORT:-8002}; RR=${RR_PORT:-8003}
fail=0
ok()  { echo "  [OK]   $*"; }
bad() { echo "  [FAIL] $*"; fail=1; }

echo "== 1. 모델 목록"
for p in $LLM $EMB $RR; do
  m=$(curl -s --max-time 5 "http://$H:$p/v1/models" | python3 -c "import json,sys;print(json.load(sys.stdin)['data'][0]['id'])" 2>/dev/null)
  [ -n "$m" ] && ok "port $p -> $m" || bad "port $p 응답 없음"
done

echo "== 2. 임베딩 (bge-m3)"
dim=$(curl -s --max-time 30 "http://$H:$EMB/v1/embeddings" -H 'Content-Type: application/json' \
  -d '{"model":"bge-m3","input":["출장 종료 후 여비 정산 기한","숙박비 상한액"]}' \
  | python3 -c "import json,sys;d=json.load(sys.stdin)['data'];print(len(d),len(d[0]['embedding']))" 2>/dev/null)
[ "$dim" = "2 1024" ] && ok "2건, 1024차원" || bad "임베딩 결과 이상: '$dim'"

echo "== 3. 리랭크 (bge-reranker-v2-m3)"
top=$(curl -s --max-time 30 "http://$H:$RR/rerank" -H 'Content-Type: application/json' \
  -d '{"model":"bge-reranker","query":"출장 다녀온 뒤 며칠 안에 정산해야 하나요?",
       "documents":["숙박비는 숙박하는 밤의 수에 따라 지급한다.",
                    "출장자는 출장 종료일 다음 날을 기점으로 7일 이내에 증빙서를 회계담당부서에 제출하여야 한다.",
                    "직원채용은 공개경쟁시험으로 한다."]}' \
  | python3 -c "import json,sys;r=json.load(sys.stdin)['results'];print(r[0]['index'],round(r[0]['relevance_score'],3))" 2>/dev/null)
[ "${top%% *}" = "1" ] && ok "정산 조문이 1위 (index score = $top)" || bad "리랭크 결과 이상: '$top'"

echo "== 4. 한국어 생성 + JSON 스키마 강제 (EXAONE)"
start=$(date +%s.%N)
out=$(curl -s --max-time 120 "http://$H:$LLM/v1/chat/completions" -H 'Content-Type: application/json' -d '{
  "model":"llm","temperature":0,"max_tokens":300,
  "messages":[{"role":"system","content":"주어진 근거 조문만 사용해 한국어로 답한다."},
              {"role":"user","content":"근거: [천문연 여비규정 제27조①] 출장자는 출장 종료일 다음 날을 기점으로 7일 이내에 출장을 확인할 수 있는 증빙서를 회계담당부서에 제출하여야 한다.\n질문: 출장 끝나고 10일 지났는데 증빙을 안 냈어요. 문제가 있나요?"}],
  "response_format":{"type":"json_schema","json_schema":{"name":"answer","schema":{
     "type":"object","required":["결론","기한_일수","설명"],
     "properties":{"결론":{"type":"string","enum":["해당","해당없음","조건부","판단불가"]},
                   "기한_일수":{"type":"integer"},"설명":{"type":"string"}}}}}}')
secs=$(python3 -c "import time;print(round(time.time()-$start,1))")
ans=$(echo "$out" | python3 -c "import json,sys;print(json.load(sys.stdin)['choices'][0]['message']['content'])" 2>/dev/null)
if echo "$ans" | python3 -c "import json,sys;d=json.loads(sys.stdin.read());assert d['기한_일수']==7" 2>/dev/null; then
  ok "${secs}s  $ans"
else
  bad "생성 결과 이상 (${secs}s): ${ans:-$out}"
fi

echo
[ $fail = 0 ] && echo "모든 확인 통과" || echo "실패 항목 있음: docker compose logs --tail 50 <서비스명>"
exit $fail
