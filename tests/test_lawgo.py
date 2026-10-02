from datetime import date
from pathlib import Path

import respx

from reg.sources.lawgo.sync import sync_laws
from reg.sources.lawgo.client import LawGoClient, norm_name, parse_search
from reg.platform.http import PoliteClient
from reg.platform.storage.blob import LocalBlobStore

FX = Path(__file__).parent / "fixtures"
B = "https://www.law.go.kr/DRF"


def test_norm_name_ignores_spaces_and_middle_dots():
    assert norm_name("설립·운영 및 육성") == norm_name("설립ㆍ운영 및육성")


def test_parse_search():
    rows = parse_search((FX / "lawgo_search.xml").read_bytes())
    assert [r.mst for r in rows] == ["283849", "288335", "289003"]
    r = rows[0]
    assert (r.law_id, r.name, r.kind, r.status) == ("013774", "국가연구개발혁신법", "법률", "현행")
    assert r.promulgated_on == date(2026, 3, 10) and r.effective_on == date(2026, 9, 11)


@respx.mock
def test_sync_fetches_once_then_skips_until_mst_changes(conn, tmp_path):
    respx.get(f"{B}/lawSearch.do").respond(200, content=(FX / "lawgo_search.xml").read_bytes())
    svc = respx.get(f"{B}/lawService.do").respond(200, content=(FX / "lawgo_service_283849.xml").read_bytes())
    client = LawGoClient(PoliteClient("lawgo", 0, sleep=lambda s: None), oc="test")
    blob = LocalBlobStore(tmp_path)
    st = sync_laws(conn, client, blob, ["국가연구개발혁신법", "없는 법"])
    assert st["fetched"] == 1 and st["not_found"] == ["없는 법"] and svc.call_count == 1
    ev = conn.execute("SELECT payload FROM regulation.outbox WHERE topic='regulation.law_fetched'").fetchall()
    assert ev[0]["payload"]["mst"] == "283849"
    st2 = sync_laws(conn, client, blob, ["국가연구개발혁신법"])
    assert st2["fetched"] == 0 and svc.call_count == 1
    w = conn.execute("SELECT * FROM regulation.law_watch WHERE law_id='013774'").fetchone()
    assert w["last_mst"] == "283849" and str(w["effective_on"]) == "2026-09-11"
