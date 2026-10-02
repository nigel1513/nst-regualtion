from datetime import date
from pathlib import Path

import pytest

from reg.core.model import Prov
from reg.sources.lawgo.config import LawgoConfig, load_config
from reg.sources.lawgo.errors import LawGoError, ResponseChanged
from reg.sources.lawgo.sync import Ctx, canary, last_success, run_daily, run_full, sync_daily, sync_full
from reg.sources.lawgo.xml import parse_list
from tests.sources.lawgo.helpers import (
    FakeClient,
    admbyl_list,
    admrul_body,
    admrul_list,
    law_body,
    law_list,
    licbyl_list,
    load_reg,
    mirror_law,
)

FX = Path(__file__).parent / "fixtures"
CFG = LawgoConfig(page_size=2, annex_body_limit=10)
ART = {1: ("목적", "이 영은 목적을 정한다.")}
RND = "국가연구개발사업 연구개발비 사용 기준"


def lr(mst, law_id, name, d):
    return {"mst": mst, "law_id": law_id, "name": name, "date": d}


def test_daily_ingests_new_versions_and_stops_after_buffer(lconn, blob):
    fc = FakeClient()
    fc.lists[("law", 1, None)] = law_list([lr("11", "000011", "가법", "20261002"), lr("12", "000012", "나법", "20260930")],
                                          total=6)
    fc.lists[("law", 2, None)] = law_list([lr("13", "000013", "다법", "20260920"), lr("14", "000014", "라법", "20260901")],
                                          total=6, page=2)
    fc.lists[("law", 3, None)] = law_list([lr("15", "000015", "마법", "20260801")], total=6, page=3)
    for mst, lid, name in [("11", "000011", "가법"), ("12", "000012", "나법"), ("13", "000013", "다법"),
                           ("14", "000014", "라법")]:
        fc.bodies[("law", mst)] = law_body(lid, name, ART)
    st = sync_daily(Ctx(lconn, fc, blob, CFG), date(2026, 10, 1))
    assert st["law_new"] == 4 and st["errors"] == []
    assert [c[2] for c in fc.calls if c[:2] == ("search", "law")] == [1, 2]  # 9/24보다 오래된 행이 나온 2쪽에서 멈춘다
    assert lconn.execute("SELECT count(*) AS n FROM law.law_version WHERE is_current").fetchone()["n"] == 4


def test_daily_second_run_fetches_no_bodies(lconn, blob):
    fc = FakeClient()
    fc.lists[("law", 1, None)] = law_list([lr("11", "000011", "가법", "20261002")])
    fc.bodies[("law", "11")] = law_body("000011", "가법", ART)
    ctx = Ctx(lconn, fc, blob, CFG)
    sync_daily(ctx, date(2026, 10, 1))
    before = sum(1 for c in fc.calls if c[0] == "service")
    assert sync_daily(ctx, date(2026, 10, 1))["law_new"] == 0
    assert sum(1 for c in fc.calls if c[0] == "service") == before


def test_daily_refreshes_annexes_of_changed_law_by_id_and_stores_bodies(lconn, blob):
    fc = FakeClient()
    fc.lists[("law", 1, None)] = law_list([lr("11", "000011", "가법", "20261002")])
    fc.bodies[("law", "11")] = law_body("000011", "가법", ART)
    fc.lists[("licbyl", 1, "가법")] = licbyl_list([
        {"seq": "901", "mst": "11", "law_id": "000011", "title": "가법 별표 1", "owner": "가법"},
        {"seq": "902", "mst": "99", "law_id": "000099", "title": "가법 시행규칙 서식", "owner": "가법 시행규칙"}])
    st = sync_daily(Ctx(lconn, fc, blob, CFG), date(2026, 10, 1))
    assert st["annex_new"] == 1 and st["annex_bodies"] == 1
    assert [r["seq"] for r in lconn.execute("SELECT seq FROM law.annex").fetchall()] == ["901"]
    assert ("annex", "licbyl", "901") in fc.calls and ("file", "/LSW/flDownload.do?flSeq=9012") in fc.calls
    a = lconn.execute("SELECT html_key, pdf_key FROM law.annex WHERE seq = '901'").fetchone()
    assert (a["html_key"], a["pdf_key"]) == ("law/annex/901.html", "law/annex/901.pdf")


def test_item_error_is_isolated_and_reported(lconn, blob):
    fc = FakeClient()
    fc.lists[("law", 1, None)] = law_list([lr("11", "000011", "가법", "20261002"), lr("12", "000012", "나법", "20261002")])
    fc.bodies[("law", "11")] = law_body("000011", "가법", ART)  # 12는 본문 없음 → KeyError
    st = sync_daily(Ctx(lconn, fc, blob, CFG), date(2026, 10, 1))
    assert st["law_new"] == 1 and len(st["errors"]) == 1 and st["errors"][0].startswith("law 12 나법")


def test_run_daily_requires_full_and_does_not_advance_on_errors(lconn, blob):
    fc = FakeClient()
    with pytest.raises(LawGoError, match="sync_full"):
        run_daily(lconn, fc, blob, CFG, check=False)
    assert run_full(lconn, fc, blob, CFG, check=False)["errors"] == []
    assert last_success(lconn) is not None
    fc.lists[("law", 1, None)] = law_list([lr("12", "000012", "나법", "20261002")])  # 본문 없음
    st = run_daily(lconn, fc, blob, CFG, check=False)
    assert st["errors"]
    last = lconn.execute("SELECT kind, status FROM law.sync_run ORDER BY id DESC LIMIT 1").fetchone()
    assert (last["kind"], last["status"]) == ("daily", "failed")


def test_full_refuses_short_list_then_abolishes_missing(lconn, blob):
    for i in (1, 2, 3):
        mirror_law(lconn, blob, f"00000{i}", f"법{i}", ART, f"10{i}")
    lconn.commit()
    fc = FakeClient()
    fc.lists[("law", 1, None)] = law_list([lr("101", "000001", "법1", "20260630"), lr("102", "000002", "법2", "20260630")])
    with pytest.raises(ResponseChanged, match="너무 적습니다"):
        sync_full(Ctx(lconn, fc, blob, CFG))
    assert {r["status"] for r in lconn.execute("SELECT status FROM law.law_master").fetchall()} == {"현행"}
    st = sync_full(Ctx(lconn, fc, blob, LawgoConfig(page_size=2, abolish_min_ratio=0.5)))
    assert st["abolished"] == 1 and st["law_new"] == 0
    assert lconn.execute("SELECT status FROM law.law_master WHERE law_id = '000003'").fetchone()["status"] == "폐지"
    assert lconn.execute("SELECT law_id FROM law.change_log WHERE change = 'law_abolished'").fetchone()["law_id"] == "000003"


def _admrul_site(fc):
    fc.lists[("admrul", 1, None)] = admrul_list([
        {"seq": "2100000278740", "admrul_id": "75386", "name": RND, "date": "20260506"},
        {"seq": "2100000000001", "admrul_id": "1", "name": "무관한 훈령", "date": "20260506", "kind": "훈령"}])
    fc.bodies[("admrul", "2100000278740")] = admrul_body("75386", RND, {3: ("사용", "연구개발비는 용도에 맞게 쓴다.")})
    fc.bodies[("admrul", "2100000000001")] = admrul_body("1", "무관한 훈령", {1: ("목적", "목적이다.")}, kind="훈령")
    fc.lists[("admbyl", 1, RND)] = admbyl_list([
        {"seq": "3220087", "mst": "2100000278740", "admrul_id": "75386", "title": "간접비 신청서", "owner": RND}])


def test_selected_admrul_is_mirrored_from_citation_only(lconn, blob):
    load_reg(lconn, blob, "kr/reg/KASI/연구비", "연구개발비 관리규정",
             [Prov("a1", "article", "제1조", "목적", f"「{RND}」 제3조에 따른다.")])
    fc = FakeClient()
    _admrul_site(fc)
    st = sync_full(Ctx(lconn, fc, blob, CFG))
    assert st["catalog"] == 2 and st["admrul_new"] == 1 and st["errors"] == []
    assert ("service", "admrul", "2100000000001") not in fc.calls  # 인용되지 않은 행정규칙은 받지 않는다
    assert lconn.execute("SELECT family FROM law.law_master WHERE law_id = 'admrul:75386'").fetchone()["family"] == "admrul"
    assert lconn.execute("SELECT 1 FROM law.article WHERE law_id = 'admrul:75386' AND path = 'a3'").fetchone()
    a = lconn.execute("SELECT law_id, pdf_path FROM law.annex WHERE seq = '3220087'").fetchone()
    assert a["law_id"] == "admrul:75386" and a["pdf_path"] is None


def test_config_include_selects_admrul_without_citation(lconn, blob):
    fc = FakeClient()
    _admrul_site(fc)
    st = sync_full(Ctx(lconn, fc, blob, LawgoConfig(page_size=2, admrul_include=["무관한 훈령"])))
    assert st["admrul_new"] == 1 and ("service", "admrul", "2100000000001") in fc.calls


def test_canary_on_recorded_responses_and_names_the_broken_tag():
    fc = FakeClient()
    fc.lists[("law", 1, None)] = (FX / "law_list_ddes_p1.xml").read_bytes()
    fc.lists[("admrul", 1, None)] = (FX / "admrul_list_ddes_p1.xml").read_bytes()
    probe = parse_list("law", fc.lists[("law", 1, None)]).rows[0].mst
    fc.bodies[("law", probe)] = (FX / "law_287535.xml").read_bytes()
    out = canary(fc)
    assert out["law_total"] > 5000 and out["admrul_total"] > 20000 and out["probe_articles"] > 10
    fc.lists[("law", 1, None)] = ('<?xml version="1.0" encoding="UTF-8"?><LawSearch><totalCnt>5627</totalCnt>'
                                  '<law><법령ID>1</법령ID></law></LawSearch>').encode()
    with pytest.raises(ResponseChanged, match="<법령일련번호>"):
        canary(fc)


def test_config_reads_new_and_legacy_formats(tmp_path):
    cfg = load_config()
    assert "국가연구개발혁신법" in cfg.promote_laws and RND in cfg.admrul_include and cfg.annex_store_pdf
    legacy = tmp_path / "old.yaml"
    legacy.write_text("- 가법\n- 나법\n", encoding="utf-8")
    assert load_config(legacy).promote_laws == ["가법", "나법"]
