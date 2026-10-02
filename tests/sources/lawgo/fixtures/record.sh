#!/usr/bin/env bash
# tests/sources/lawgo/fixtures/record.sh
# law.go.kr 계약 테스트 표본을 다시 받는다. 개발용 OC=test만 쓴다(운영 키를 여기에 적지 않는다). 요청 사이 1.2초.
# 사이트가 바뀌면 이 스크립트로 다시 받고 tests/sources/lawgo/test_xml_*.py, test_client.py를 돌린다.
set -euo pipefail
cd "$(dirname "$0")"
UA="NST-Regulation-Collector/0.1 (+contact: bigdatanigel1513@gmail.com)"
D="https://www.law.go.kr/DRF"
enc() { python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1]))' "$1"; }
get() { curl -sS -A "$UA" "$1" -o "$2"; echo "$2 $(wc -c < "$2")"; sleep 1.2; }

get "$D/lawSearch.do?OC=test&target=law&type=XML&sort=ddes&display=5&page=1" law_list_ddes_p1.xml
get "$D/lawSearch.do?OC=test&target=admrul&type=XML&sort=ddes&display=5&page=1" admrul_list_ddes_p1.xml
get "$D/lawSearch.do?OC=test&target=licbyl&type=XML&search=2&display=100&query=$(enc '공무원 여비 규정')" licbyl_yeobi.xml
get "$D/lawSearch.do?OC=test&target=admbyl&type=XML&search=2&display=100&query=$(enc '국가연구개발사업 연구개발비 사용 기준')" admbyl_rnd.xml
get "$D/lawService.do?OC=test&target=law&MST=287535&type=XML" law_287535.xml
get "$D/lawService.do?OC=test&target=admrul&ID=2100000285346&type=XML" admrul_2100000285346.xml
get "$D/lawService.do?OC=test&target=licbyl&ID=18272187&type=HTML" licbyl_18272187.html
get "$D/lawService.do?OC=test&target=law&MST=999999999&type=XML" law_not_found.xml
get "$D/lawSearch.do?OC=nst-unregistered-probe&target=law&type=XML&display=1" oc_rejected.xml
get "$D/lawSearch.do?target=law&type=XML&display=1" missing_oc.xml
if grep -q "OC=" licbyl_18272187.html law_287535.xml admrul_2100000285346.xml; then
  echo "경고: 저장한 본문에 OC 파라미터가 있다 — 커밋 전에 확인" >&2; exit 1
fi
