import json
import re
from pathlib import Path

import httpx
import pytest
import respx

from reg.platform.http import PoliteClient
from reg.sources.alio.canary import AlioSchemaChanged, run_canary
from reg.sources.alio.client import AlioClient, AlioError

FX = Path(__file__).parent / "fixtures"
BASE = "https://www.alio.go.kr"
L, D = "canary_list_kasi_p1.json", "canary_detail_47852.json"


def load(name: str) -> dict:
    return json.loads((FX / name).read_text(encoding="utf-8"))


def client() -> AlioClient:
    return AlioClient(PoliteClient("alio", 0, sleep=lambda s: None))


def serve(list_body: dict, detail_for: dict[str, dict], default_detail: dict | None = None):
    respx.get(f"{BASE}/occasional/findRuleList.json").respond(200, json=list_body)
    respx.get(f"{BASE}/occasional/findRuleDtl.json").mock(side_effect=lambda req: httpx.Response(
        200, json=detail_for.get(req.url.params["seq"], default_detail)))


@respx.mock
def test_recorded_responses_pass():
    serve(load(L), {"47852": load(D)})
    r = run_canary(client())
    assert r["ok"] is True and r["seq"] == "47852" and r["rows"] >= 1 and r["files"] >= 1 and r["warning"] is None


@pytest.mark.parametrize("mutate, message", [
    (lambda l, d: l["data"]["result"][0].pop("title"), "findRuleList data.result[0].title 없음"),
    (lambda l, d: l["data"]["result"][0].pop("submissionNo"), "findRuleList data.result[0].submissionNo 없음"),
    (lambda l, d: l["data"]["page"].pop("totalPage"), "findRuleList data.page.totalPage 없음"),
    (lambda l, d: l["data"]["page"].__setitem__("totalPage", "many"), "findRuleList data.page.totalPage 숫자 아님"),
    (lambda l, d: l["data"].__setitem__("result", [dict(r, apbaId="X") for r in l["data"]["result"]]),
     "apbaId=C0266 행 없음"),
    (lambda l, d: l.pop("status"), "findRuleList status 없음"),
    (lambda l, d: d["data"].pop("title"), "findRuleDtl(seq=47852) data.title 없음"),
    (lambda l, d: d["data"].__setitem__("bFiles", [{"fileNo": 1}]), "findRuleDtl(seq=47852) data.bFiles 형식 str 아님 (list)"),
    (lambda l, d: d["data"].__setitem__("bFiles", "a.pdf;b.pdf"), "findRuleDtl(seq=47852) data.bFiles 파일 목록을 읽지 못함"),
    (lambda l, d: d["data"].__setitem__("retryRvsnYmd", "17/01/2024"), "findRuleDtl(seq=47852) data.retryRvsnYmd 날짜 형식 아님"),
])
@respx.mock
def test_schema_changes_fail_with_precise_message(mutate, message):
    l, d = load(L), load(D)
    mutate(l, d)
    serve(l, {"47852": d})
    with pytest.raises(AlioSchemaChanged, match=re.escape(message)):
        run_canary(client())


@respx.mock
def test_outage_status_is_not_reported_as_schema_change():
    respx.get(f"{BASE}/occasional/findRuleList.json").respond(200, json={"status": "fail", "message": "점검", "data": None})
    with pytest.raises(AlioError, match="status=fail"):
        run_canary(client())


@respx.mock
def test_maintenance_html_is_not_reported_as_schema_change():
    respx.get(f"{BASE}/occasional/findRuleList.json").respond(200, text="<html>점검중</html>")
    with pytest.raises(AlioError, match="JSON 아님"):
        run_canary(client())


@respx.mock
def test_missing_canary_seq_falls_back_to_another_listed_rule():
    l, d = load(L), load(D)
    other = next(str(r["seq"]) for r in l["data"]["result"] if r["apbaId"] == "C0266" and str(r["seq"]) != "47852")
    serve(l, {"47852": {"status": "fail", "message": "없음", "data": None}}, default_detail=d)
    r = run_canary(client())
    assert r["seq"] == other and "47852" in r["warning"]


def test_active_institutions_runs_canary_first(app_env, monkeypatch):
    from reg.sources.alio import tasks

    def broken():
        raise AlioSchemaChanged("ALIO 응답 구조 변경: findRuleList data.result[0].title 없음")

    monkeypatch.setattr(tasks, "canary_check", broken)
    with pytest.raises(AlioSchemaChanged, match="title 없음"):
        tasks.active_institutions()


def test_cli_canary_exit_codes(monkeypatch):
    from typer.testing import CliRunner

    from reg.cli import app
    from reg.sources.alio import tasks

    runner = CliRunner()
    monkeypatch.setattr(tasks, "canary_check", lambda: {"ok": True, "seq": "47852"})
    assert runner.invoke(app, ["alio", "canary"]).exit_code == 0

    def changed():
        raise AlioSchemaChanged("ALIO 응답 구조 변경: findRuleDtl(seq=47852) data.bFiles 없음")

    monkeypatch.setattr(tasks, "canary_check", changed)
    r = runner.invoke(app, ["alio", "canary"])
    assert r.exit_code == 2 and "bFiles 없음" in r.output

    def outage():
        raise AlioError("/occasional/findRuleList.json: JSON 아님")

    monkeypatch.setattr(tasks, "canary_check", outage)
    assert runner.invoke(app, ["alio", "canary"]).exit_code == 1
