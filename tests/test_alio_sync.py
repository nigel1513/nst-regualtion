import json
from pathlib import Path

import httpx
import pytest
import respx

from reg.sources.alio.client import AlioClient
from reg.sources.alio.sync import load_institutions, sync_institution
from reg.platform.http import PoliteClient, StopCollecting
from reg.platform.storage.blob import LocalBlobStore

FX = Path(__file__).parent / "fixtures"
BASE = "https://www.alio.go.kr"
PDF_A, PDF_B = b"%PDF-1.4 A", b"%PDF-1.4 B"


def setup_inst(conn, tmp_path):
    cfg = tmp_path / "i.yaml"
    cfg.write_text("- {code: KASI, name: 한국천문연구원, kind: GRI, alio_apba_id: C0266, alio_name: 한국천문연구원}\n")
    return load_institutions(conn, cfg)[0]


def mock_alio(files_by_no: dict[str, bytes], bfiles: str):
    lst = json.loads((FX / "alio_list_kasi_p1.json").read_text())
    lst["data"]["result"] = lst["data"]["result"][:1]  # seq 47852 하나만
    det = json.loads((FX / "alio_detail.json").read_text())
    det["data"]["bFiles"] = bfiles
    respx.get(f"{BASE}/occasional/findRuleList.json").respond(200, json=lst)
    respx.get(f"{BASE}/occasional/findRuleDtl.json").respond(200, json=det)
    dl = respx.get(f"{BASE}/download/rulefiledown.json")
    def respond(req):
        body = files_by_no[req.url.params["fileNo"]]
        return httpx.Response(403) if body is None else httpx.Response(200, content=body)
    dl.side_effect = respond
    return dl


def run(conn, tmp_path, inst):
    alio = AlioClient(PoliteClient("alio", 0, sleep=lambda s: None))
    return sync_institution(conn, alio, LocalBlobStore(tmp_path / "blob"), inst)


def events(conn):
    return conn.execute("SELECT payload FROM regulation.outbox WHERE topic='regulation.source_fetched'"
                        " ORDER BY id").fetchall()


@respx.mock
def test_first_run_fetches_all_and_emits(conn, tmp_path):
    inst = setup_inst(conn, tmp_path)
    mock_alio({"1": PDF_A, "2": PDF_B}, "1|a.pdf,2|b.pdf")
    st = run(conn, tmp_path, inst)
    assert st["files_fetched"] == 2 and st["files_new_content"] == 2
    assert [e["payload"]["file_no"] for e in events(conn)] == ["1", "2"]
    rule = conn.execute("SELECT * FROM regulation.alio_rule WHERE seq='47852'").fetchone()
    assert str(rule["revised_on"]) == "2024-01-17"


@respx.mock
def test_second_run_is_noop(conn, tmp_path):
    inst = setup_inst(conn, tmp_path)
    dl = mock_alio({"1": PDF_A}, "1|a.pdf")
    run(conn, tmp_path, inst)
    calls = dl.call_count
    st = run(conn, tmp_path, inst)
    assert st["details_fetched"] == 0 and dl.call_count == calls and len(events(conn)) == 1


@respx.mock
def test_new_file_no_with_same_content_records_mapping_without_event(conn, tmp_path):
    inst = setup_inst(conn, tmp_path)
    mock_alio({"1": PDF_A}, "1|a.pdf")
    run(conn, tmp_path, inst)
    respx.reset()
    mock_alio({"1": PDF_A, "9": PDF_A}, "1|a.pdf,9|a-재게시.pdf")
    conn.execute("UPDATE regulation.alio_rule SET list_fingerprint='old'")
    conn.commit()
    st = run(conn, tmp_path, inst)
    assert st["files_fetched"] == 1 and st["files_new_content"] == 0 and len(events(conn)) == 1
    n = conn.execute("SELECT count(*) AS n FROM regulation.alio_rule_file").fetchone()["n"]
    assert n == 2


@respx.mock
def test_html_instead_of_file_is_rejected(conn, tmp_path):
    inst = setup_inst(conn, tmp_path)
    mock_alio({"1": b"<html>error</html>"}, "1|a.pdf")
    st = run(conn, tmp_path, inst)
    f = conn.execute("SELECT * FROM regulation.alio_rule_file WHERE file_no='1'").fetchone()
    assert st["files_rejected"] == 1 and f["status"] == "rejected" and f["source_document_id"] is None
    assert events(conn) == []


@respx.mock
def test_stop_midway_then_resume(conn, tmp_path):
    inst = setup_inst(conn, tmp_path)
    mock_alio({"1": PDF_A, "2": None}, "1|a.pdf,2|b.pdf")  # 두 번째 파일에서 403 → 중지
    with pytest.raises(StopCollecting):
        run(conn, tmp_path, inst)
    conn.rollback()
    assert conn.execute("SELECT count(*) AS n FROM regulation.alio_rule_file").fetchone()["n"] == 0
    respx.reset()
    mock_alio({"1": PDF_A, "2": PDF_B}, "1|a.pdf,2|b.pdf")
    st = run(conn, tmp_path, inst)
    assert st["files_fetched"] == 2


@respx.mock
def test_rejected_file_is_retried_on_next_run(conn, tmp_path):
    inst = setup_inst(conn, tmp_path)
    mock_alio({"1": b"<html>error</html>"}, "1|a.pdf")
    run(conn, tmp_path, inst)
    respx.reset()
    mock_alio({"1": PDF_A}, "1|a.pdf")  # 목록 지문은 그대로
    st = run(conn, tmp_path, inst)
    f = conn.execute("SELECT * FROM regulation.alio_rule_file WHERE file_no='1'").fetchone()
    assert st["files_fetched"] == 1 and f["status"] == "fetched" and f["source_document_id"] is not None
    assert len(events(conn)) == 1


@respx.mock
def test_duplicate_file_no_does_not_break_the_run(conn, tmp_path):
    inst = setup_inst(conn, tmp_path)
    mock_alio({"1": PDF_A}, "1|a.pdf,1|a.pdf")
    st = run(conn, tmp_path, inst)
    assert st["files_fetched"] == 1
    st2 = run(conn, tmp_path, inst)  # 다시 실행해도 실패하지 않는다
    assert st2["files_fetched"] == 0
