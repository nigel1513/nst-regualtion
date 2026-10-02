from datetime import datetime

import httpx
import pytest
import respx

from reg.platform.http import PoliteClient, StopCollecting
from reg.platform.storage.blob import LocalBlobStore
from reg.sources.alio.client import AlioClient
from reg.sources.alio.sync import get_institution, load_institutions, sync_institution

BASE = "https://www.alio.go.kr"


def row(seq: str) -> dict:
    return {"seq": seq, "title": f"규정{seq}", "apbaId": "C0266", "insdRuleDivis": None, "submissionNo": "1",
            "ruleStDa": "2024.01.17", "idate": "2024.01.17", "crctYn": "N", "reSbmtYn": "N"}


def serve(pages: list[list[str]], broken_seq: str | None = None):
    def lst(req):
        p = int(req.url.params["pageNo"])
        return httpx.Response(200, json={"status": "success", "data": {
            "page": {"totalPage": len(pages)}, "result": [row(s) for s in pages[p - 1]]}})

    def det(req):
        seq = req.url.params["seq"]
        if seq == broken_seq:
            return httpx.Response(500)
        return httpx.Response(200, json={"status": "success", "data": {
            "title": f"규정{seq}", "insdRuleDivis": None, "retryRvsnYmd": "2024.01.17", "idate": "2022.05.25",
            "bFiles": f"{seq}0|규정{seq}.pdf"}})

    respx.get(f"{BASE}/occasional/findRuleList.json").mock(side_effect=lst)
    respx.get(f"{BASE}/occasional/findRuleDtl.json").mock(side_effect=det)
    respx.get(f"{BASE}/download/rulefiledown.json").mock(
        side_effect=lambda req: httpx.Response(200, content=b"%PDF-1.4 " + req.url.params["fileNo"].encode()))


def inst(conn, tmp_path):
    cfg = tmp_path / "i.yaml"
    cfg.write_text("- {code: KASI, name: 한국천문연구원, kind: GRI, alio_apba_id: C0266, alio_name: 한국천문연구원}\n",
                   encoding="utf-8")
    return load_institutions(conn, cfg)[0]


def run(conn, tmp_path, i, limit=None):
    alio = AlioClient(PoliteClient("alio", 0, sleep=lambda s: None))
    return sync_institution(conn, alio, LocalBlobStore(tmp_path / "blob"), i, limit=limit)


@respx.mock
def test_full_traversal_is_complete_and_every_seen_rule_is_after_start(conn, tmp_path):
    i = inst(conn, tmp_path)
    serve([["1", "2"], ["3"]])
    st = run(conn, tmp_path, i)
    assert st["complete"] is True and st["rules_seen"] == 3
    started = datetime.fromisoformat(st["started_at"])
    assert started.tzinfo is not None
    rows = conn.execute("SELECT seq, last_seen_at FROM regulation.alio_rule ORDER BY seq").fetchall()
    assert [r["seq"] for r in rows] == ["1", "2", "3"] and all(r["last_seen_at"] >= started for r in rows)
    metas = [r["source_meta"] for r in conn.execute("SELECT source_meta FROM regulation.source_document").fetchall()]
    assert len(metas) == 3 and all(m["institution_code"] == "KASI" and m["institution_name"] == "한국천문연구원"
                                   for m in metas)   # overview §2.8: 수집 시점의 기관명
    st2 = run(conn, tmp_path, i)   # 지문이 같아 상세를 건너뛰는 경로도 last_seen_at을 started_at 이후로 올려야 한다
    started2 = datetime.fromisoformat(st2["started_at"])
    assert st2["complete"] is True and st2["details_fetched"] == 0
    assert all(r["last_seen_at"] >= started2 for r in conn.execute(
        "SELECT last_seen_at FROM regulation.alio_rule").fetchall())


@respx.mock
def test_limit_is_never_complete(conn, tmp_path):
    i = inst(conn, tmp_path)
    serve([["1", "2"]])
    assert run(conn, tmp_path, i, limit=1)["complete"] is False
    assert run(conn, tmp_path, i, limit=10)["complete"] is False   # 상한보다 적게 끝나도 상한을 준 실행은 대조에 쓰지 않는다


@respx.mock
def test_exception_mid_list_propagates(conn, tmp_path):
    i = inst(conn, tmp_path)
    serve([["1", "2"]], broken_seq="2")
    with pytest.raises(StopCollecting):
        run(conn, tmp_path, i)
    assert [r["seq"] for r in conn.execute("SELECT seq FROM regulation.alio_rule").fetchall()] == ["1"]


def test_load_institutions_honours_active_and_null_apba(conn, tmp_path):
    cfg = tmp_path / "a.yaml"
    cfg.write_text(
        "- {code: KASI, name: 한국천문연구원, kind: GRI, alio_apba_id: C0266, alio_name: 한국천문연구원,"
        " aliases: [천문연, 천문연구원]}\n"
        "- {code: KBSI, name: 한국기초과학지원연구원, kind: GRI, alio_apba_id: C0177, alio_name: 한국기초과학지원연구원, active: false}\n"
        "- {code: NSR, name: 국가보안기술연구소, kind: GRI, alio_apba_id: null, alio_name: null, active: false}\n",
        encoding="utf-8")
    assert [r["code"] for r in load_institutions(conn, cfg)] == ["KASI"]
    assert get_institution(conn, "KBSI")["active"] is False and get_institution(conn, "NSR")["alio_apba_id"] is None
    assert get_institution(conn, "NOPE") is None
    assert get_institution(conn, "KASI")["aliases"] == ["천문연", "천문연구원"] and get_institution(conn, "NSR")["aliases"] == []
    # 기관 추가 = 한 줄의 active를 true로
    cfg.write_text(cfg.read_text(encoding="utf-8").replace("active: false}", "active: true}", 1), encoding="utf-8")
    assert [r["code"] for r in load_institutions(conn, cfg)] == ["KASI", "KBSI"]
