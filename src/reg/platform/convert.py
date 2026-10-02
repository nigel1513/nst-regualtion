"""HWP·HWPX → 보기용 PDF. 운영: LibreOffice+H2Orestart 컨테이너 (infra/converter)."""
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Protocol


class ConversionError(Exception):
    pass


class Converter(Protocol):
    def to_pdf(self, data: bytes, ext: str) -> bytes: ...


class DockerConverter:
    def __init__(self, image: str = "nst-regulation/converter:0.1", timeout: float = 120.0):
        self.image, self.timeout = image, timeout

    def to_pdf(self, data: bytes, ext: str) -> bytes:
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / f"in.{ext}"
            src.write_bytes(data)
            os.chmod(d, 0o777)
            cmd = ["docker", "run", "--rm", "-u", f"{os.getuid()}:{os.getgid()}", "-e", "HOME=/tmp",
                   "--network", "none", "-v", f"{d}:/work", self.image, f"/work/in.{ext}"]
            try:
                r = subprocess.run(cmd, capture_output=True, timeout=self.timeout)
            except (subprocess.TimeoutExpired, FileNotFoundError) as e:
                raise ConversionError(f"변환기 실행 실패: {e!r}") from e
            out = Path(d) / "out" / "in.pdf"
            if r.returncode != 0 or not out.exists():
                raise ConversionError(f"변환 실패 (rc={r.returncode}): {r.stderr.decode(errors='replace')[-300:]}")
            pdf = out.read_bytes()
            if not pdf.startswith(b"%PDF"):
                raise ConversionError("변환 결과가 PDF가 아님")
            return pdf
