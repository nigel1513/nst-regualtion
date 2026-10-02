"""HWP·HWPX → 보기용 PDF. 운영: LibreOffice+H2Orestart 컨테이너 (infra/converter)."""
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Protocol

import httpx

from reg.platform.settings import Settings, get_settings


class ConversionError(Exception):
    pass


class Converter(Protocol):
    def to_pdf(self, data: bytes, ext: str) -> bytes: ...


class DockerConverter:
    def __init__(self, image: str = "nst-regulation/converter:0.2", timeout: float = 120.0):
        self.image, self.timeout = image, timeout

    def to_pdf(self, data: bytes, ext: str) -> bytes:
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / f"in.{ext}"
            src.write_bytes(data)
            os.chmod(d, 0o777)
            cmd = ["docker", "run", "--rm", "-u", f"{os.getuid()}:{os.getgid()}", "-e", "HOME=/tmp",
                   "--network", "none", "-v", f"{d}:/work", self.image, f"/work/in.{ext}"]
            try:
                r = subprocess.run(cmd, capture_output=True, timeout=self.timeout, check=False)
            except (subprocess.TimeoutExpired, FileNotFoundError) as e:
                raise ConversionError(f"변환기 실행 실패: {e!r}") from e
            out = Path(d) / "out" / "in.pdf"
            if r.returncode != 0 or not out.exists():
                raise ConversionError(f"변환 실패 (rc={r.returncode}): {r.stderr.decode(errors='replace')[-300:]}")
            pdf = out.read_bytes()
            if not pdf.startswith(b"%PDF"):
                raise ConversionError("변환 결과가 PDF가 아님")
            return pdf


CONVERT_KINDS = ("hwp", "hwpx")


class HttpConverter:
    """상주 변환기 서비스(infra/converter/server.py)를 부른다. compose 안(Airflow)에서 쓴다 (spec D-2 B안)."""

    def __init__(self, base_url: str, timeout: float = 180.0, tries: int = 3, wait: float = 2.0):
        self.base_url, self.timeout, self.tries, self.wait = base_url.rstrip("/"), timeout, tries, wait

    def to_pdf(self, data: bytes, ext: str) -> bytes:
        if ext not in CONVERT_KINDS:
            raise ConversionError(f"변환할 수 없는 형식: {ext}")
        last: Exception | None = None
        for i in range(self.tries):
            try:
                r = httpx.post(f"{self.base_url}/convert", params={"kind": ext}, content=data,
                               headers={"Content-Type": "application/octet-stream"}, timeout=self.timeout)
                break
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:  # 변환기 재시작 중일 수 있다
                last = e
                if i + 1 < self.tries:
                    time.sleep(self.wait)
            except httpx.HTTPError as e:
                raise ConversionError(f"변환기 호출 실패: {e!r}") from e
        else:
            raise ConversionError(f"변환기에 연결할 수 없음 ({self.base_url}): {last!r}") from last
        if r.status_code != 200:
            raise ConversionError(f"변환 실패 (HTTP {r.status_code}): {r.text[:300]}")
        if not r.content.startswith(b"%PDF"):
            raise ConversionError("변환 결과가 PDF가 아님")
        return r.content


def get_converter(settings: Settings | None = None) -> Converter:
    s = settings or get_settings()
    return HttpConverter(s.converter_url) if s.converter_url else DockerConverter()
