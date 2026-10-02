"""실제 변환기 이미지(0.2)를 HTTP 서비스로 띄워 HWP 표본을 변환한다. 먼저: docker build -t nst-regulation/converter:0.2 infra/converter"""
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from reg.platform.convert import HttpConverter

IMAGE = "nst-regulation/converter:0.2"
HWP = Path(__file__).resolve().parents[1] / "fixtures" / "samples" / "nst-yeobi-18.hwp"


@pytest.mark.integration
def test_converter_service_converts_hwp_sample():
    from testcontainers.core.container import DockerContainer

    if subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, check=False).returncode != 0:
        pytest.skip(f"{IMAGE} 없음: docker build -t {IMAGE} infra/converter")
    c = (DockerContainer(IMAGE).with_exposed_ports(8080).with_env("HOME", "/tmp")
         .with_kwargs(entrypoint=["python3", "/srv/converter/server.py"], user="65534:65534"))
    with c:
        url = f"http://{c.get_container_host_ip()}:{c.get_exposed_port(8080)}"
        for _ in range(30):
            try:
                if httpx.get(f"{url}/healthz", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(1)
        pdf = HttpConverter(url, timeout=300).to_pdf(HWP.read_bytes(), "hwp")
    assert pdf.startswith(b"%PDF") and len(pdf) > 50_000
