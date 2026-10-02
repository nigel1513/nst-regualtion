import contextlib
import json

from typer.testing import CliRunner

from reg.cli import app
from tests.ocr.fx import TEXT_PDF, FakeOcr, lines_of
from tests.test_process import TODAY


def _patch_engine(monkeypatch, blob, fake):
    import reg.platform.mineru as M
    import reg.platform.ocr as O
    import reg.platform.storage.blob as B

    monkeypatch.setattr(B, "blob_store", lambda s=None: blob)
    monkeypatch.setattr(M.MineruClient, "from_settings", staticmethod(lambda s=None, **kw: None))
    monkeypatch.setattr(O, "MineruOcr", lambda client, **kw: fake)


def test_tasks_run_pending_records_pipeline_run(conn, blob, seeded, monkeypatch):
    import reg.ocr.tasks as T
    from reg.core.ingest.process import process_once

    process_once(conn, blob, today=TODAY)
    monkeypatch.setattr(T, "open_conn", lambda: contextlib.nullcontext(conn))
    _patch_engine(monkeypatch, blob, FakeOcr(lines_of(TEXT_PDF)))
    out = T.run_pending(limit=5)
    assert out["ready"] == 1 and out["processed"] == 1 and out["unavailable"] is False
    assert json.loads(json.dumps(out)) == out
    run = conn.execute("SELECT task_id, status, stats FROM ops.pipeline_run").fetchone()
    assert (run["task_id"], run["status"], run["stats"]["ready"]) == ("ocr.run_pending", "success", 1)


def test_tasks_run_pending_reports_gpu_down_without_failing(conn, blob, seeded, monkeypatch):
    import reg.ocr.tasks as T
    from reg.core.ingest.process import process_once

    process_once(conn, blob, today=TODAY)
    monkeypatch.setattr(T, "open_conn", lambda: contextlib.nullcontext(conn))
    _patch_engine(monkeypatch, blob, FakeOcr(healthy=False))
    out = T.run_pending()
    assert out["unavailable"] is True and out["processed"] == 0
    assert conn.execute("SELECT status FROM ops.pipeline_run").fetchone()["status"] == "success"


def test_cli_lists_ocr_commands():
    r = CliRunner().invoke(app, ["ocr", "--help"])
    assert r.exit_code == 0
    for name in ("run", "enqueue-low-text", "status"):
        assert name in r.output


def test_cli_status_prints_json(conn, blob, seeded, monkeypatch):
    import reg.ocr.cli as C
    from reg.core.ingest.process import process_once

    process_once(conn, blob, today=TODAY)
    monkeypatch.setattr(C, "open_conn", lambda: contextlib.nullcontext(conn))
    monkeypatch.setattr(C, "mineru_available", lambda url, key: False)
    r = CliRunner().invoke(app, ["ocr", "status"])
    assert r.exit_code == 0, r.output
    out = json.loads(r.output)
    assert out["queued"] == 1 and out["mineru_available"] is False


def test_cli_run_all_tries_each_event_once(conn, blob, seeded, monkeypatch):
    """리뷰 Important #2: --all 반복 안에서도 한 이벤트는 한 번만 시도한다."""
    import reg.ocr.tasks as T
    from reg.core.ingest.process import process_once

    process_once(conn, blob, today=TODAY)
    monkeypatch.setattr(T, "open_conn", lambda: contextlib.nullcontext(conn))
    fake = FakeOcr(fail=99)
    _patch_engine(monkeypatch, blob, fake)
    r = CliRunner().invoke(app, ["ocr", "run", "--all"])
    assert r.exit_code == 0, r.output
    assert fake.calls == 1 and json.loads(r.output)["retry"] == 1
