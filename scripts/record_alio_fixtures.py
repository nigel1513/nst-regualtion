"""ALIO 계약 테스트용 실제 응답 기록. 사이트가 바뀌었을 때 다시 실행해 git diff로 바뀐 필드를 본다.

요청 3회, 간격 1.5초. 실행: uv run python scripts/record_alio_fixtures.py
"""
import json
import time
from pathlib import Path

import httpx

from reg.platform.settings import USER_AGENT

BASE = "https://www.alio.go.kr"
OUT = Path(__file__).resolve().parents[1] / "tests/sources/alio/fixtures"
REQUESTS = [
    ("canary_list_kasi_p1.json", "/occasional/findRuleList.json", {"type": "apbaNa", "word": "한국천문연구원", "pageNo": 1}),
    ("canary_detail_47852.json", "/occasional/findRuleDtl.json", {"seq": "47852"}),
    ("canary_list_nst_p1.json", "/occasional/findRuleList.json", {"type": "apbaNa", "word": "국가과학기술연구회", "pageNo": 1}),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=False) as c:
        for i, (name, path, params) in enumerate(REQUESTS):
            if i:
                time.sleep(1.5)
            r = c.get(BASE + path, params=params)
            r.raise_for_status()
            (OUT / name).write_text(json.dumps(r.json(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            print(name, r.status_code, len(r.content))


if __name__ == "__main__":
    main()
