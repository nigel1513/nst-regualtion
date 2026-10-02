"""기록된 실제 응답(fixtures/canary_*)으로 client 파싱을 시험한다. 네트워크 없이 돈다."""
import json
from pathlib import Path

import respx

from reg.platform.http import PoliteClient
from reg.sources.alio.client import FINGERPRINT_KEYS, AlioClient

FX = Path(__file__).parent / "fixtures"
BASE = "https://www.alio.go.kr"


def load(name: str) -> dict:
    return json.loads((FX / name).read_text(encoding="utf-8"))


def client() -> AlioClient:
    return AlioClient(PoliteClient("alio", 0, sleep=lambda s: None))


@respx.mock
def test_recorded_lists_parse_into_rows():
    for name, word, apba in (("canary_list_kasi_p1.json", "한국천문연구원", "C0266"),
                             ("canary_list_nst_p1.json", "국가과학기술연구회", "C0909")):
        body = load(name)
        body["data"]["page"]["totalPage"] = 1   # 기록은 1쪽뿐: 쪽 넘김 없이 끝나게
        respx.get(f"{BASE}/occasional/findRuleList.json").respond(200, json=body)
        rows = list(client().list_rules(word, apba))
        assert rows and all(r.apba_id == apba and r.title for r in rows)
        assert all(r.fingerprint.count("|") == len(FINGERPRINT_KEYS) - 1 for r in rows)


@respx.mock
def test_recorded_detail_parses_revision_files():
    respx.get(f"{BASE}/occasional/findRuleDtl.json").respond(200, json=load("canary_detail_47852.json"))
    d = client().detail("47852")
    assert d.title and d.revised_on is not None and d.posted_on is not None
    assert len(d.files) >= 2 and all(no.isdigit() and name for no, name in d.files)   # bFiles = 개정 이력 전체
