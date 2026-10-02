"""변환기 HTTP 계약: LibreOffice 없이 convert만 바꿔 끼워 검사한다."""
import importlib.util
import threading
from pathlib import Path

import httpx
import pytest

SERVER = Path(__file__).resolve().parents[2] / "infra" / "converter" / "server.py"


def _load():
    spec = importlib.util.spec_from_file_location("converter_server", SERVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def server(monkeypatch):
    mod = _load()
    srv = mod.ThreadingHTTPServer(("127.0.0.1", 0), mod.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield mod, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def test_healthz_and_404(server):
    _, url = server
    assert httpx.get(f"{url}/healthz").text == "ok"
    assert httpx.get(f"{url}/nope").status_code == 404


def test_convert_ok(server, monkeypatch):
    mod, url = server
    seen = {}

    def fake(data, kind):
        seen.update(data=data, kind=kind)
        return b"%PDF-1.7 fake"

    monkeypatch.setattr(mod.Handler, "convert", staticmethod(fake))
    r = httpx.post(f"{url}/convert", params={"kind": "hwp"}, content=b"HWP")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content == b"%PDF-1.7 fake" and seen == {"data": b"HWP", "kind": "hwp"}


@pytest.mark.parametrize("params, body, code", [({"kind": "doc"}, b"x", 400), ({"kind": "hwpx"}, b"", 400)])
def test_bad_requests(server, params, body, code):
    _, url = server
    assert httpx.post(f"{url}/convert", params=params, content=body).status_code == code


def test_failure_and_timeout_codes(server, monkeypatch):
    mod, url = server

    def failed(data, kind):
        raise mod.ConvertFailed("rc=1 깨진 파일")

    monkeypatch.setattr(mod.Handler, "convert", staticmethod(failed))
    r = httpx.post(f"{url}/convert", params={"kind": "hwp"}, content=b"x")
    assert r.status_code == 422 and "깨진 파일" in r.text

    def slow(data, kind):
        raise mod.ConvertTimeout("120초 안에 끝나지 않음")

    monkeypatch.setattr(mod.Handler, "convert", staticmethod(slow))
    assert httpx.post(f"{url}/convert", params={"kind": "hwp"}, content=b"x").status_code == 504
