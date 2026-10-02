"""HWP·HWPX → 보기용 PDF 변환 HTTP 서비스 (compose 내부 전용, 표준 라이브러리만: 이미지의 python3 = Debian 3.11).

POST /convert?kind=hwp|hwpx  본문=원본 바이트 → 200 application/pdf
GET  /healthz                → 200 ok
"""
import os
import signal
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

KINDS = ("hwp", "hwpx")
MAX_BYTES = int(os.environ.get("CONVERTER_MAX_BYTES", str(50 * 1024 * 1024)))
TIMEOUT = float(os.environ.get("CONVERTER_TIMEOUT", "120"))
PROFILE = os.environ.get("CONVERTER_PROFILE", "file:///tmp/lo-profile")
_lock = threading.Lock()  # LibreOffice 프로필 하나를 함께 쓰므로 한 번에 하나씩 변환한다


class ConvertFailed(Exception):
    pass


class ConvertTimeout(Exception):
    pass


def soffice(src: Path, outdir: Path) -> bytes:
    cmd = ["soffice", f"-env:UserInstallation={PROFILE}", "--headless", "--norestore",
           "--convert-to", "pdf", "--outdir", str(outdir), str(src)]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    try:
        _, err = p.communicate(timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)  # soffice는 soffice.bin을 자식으로 띄운다: 프로세스 그룹째 끝낸다
        p.communicate()
        raise ConvertTimeout(f"{TIMEOUT:.0f}초 안에 끝나지 않음") from None
    out = outdir / f"{src.stem}.pdf"
    if p.returncode != 0 or not out.exists():
        raise ConvertFailed(f"rc={p.returncode} {err.decode(errors='replace')[-300:]}")
    pdf = out.read_bytes()
    if not pdf.startswith(b"%PDF"):
        raise ConvertFailed("변환 결과가 PDF가 아님")
    return pdf


def convert(data: bytes, kind: str) -> bytes:
    with _lock, tempfile.TemporaryDirectory() as d:
        src = Path(d) / f"in.{kind}"
        src.write_bytes(data)
        return soffice(src, Path(d) / "out")


class Handler(BaseHTTPRequestHandler):
    server_version = "nst-converter/0.2"
    convert = staticmethod(convert)

    def _reply(self, code: int, body: bytes, ctype: str = "text/plain; charset=utf-8") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if urlparse(self.path).path == "/healthz":
            self._reply(200, b"ok")
        else:
            self._reply(404, b"not found")

    def do_POST(self) -> None:
        u = urlparse(self.path)
        if u.path != "/convert":
            return self._reply(404, b"not found")
        kind = (parse_qs(u.query).get("kind") or [""])[0]
        if kind not in KINDS:
            return self._reply(400, f"kind는 {'|'.join(KINDS)} 중 하나".encode())
        length = self.headers.get("Content-Length")
        if length is None:
            return self._reply(411, b"Content-Length required")
        try:
            n = int(length)
        except ValueError:
            return self._reply(400, b"bad Content-Length")
        if n <= 0:
            return self._reply(400, "본문이 비었음".encode())
        if n > MAX_BYTES:
            return self._reply(413, "파일이 너무 큼".encode())
        data = self.rfile.read(n)
        try:
            pdf = type(self).convert(data, kind)
        except ConvertTimeout as e:
            return self._reply(504, str(e).encode())
        except ConvertFailed as e:
            return self._reply(422, str(e).encode())
        self._reply(200, pdf, "application/pdf")

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write(f"converter {self.address_string()} - {fmt % args}\n")


def main() -> None:
    port = int(os.environ.get("CONVERTER_PORT", "8080"))
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
