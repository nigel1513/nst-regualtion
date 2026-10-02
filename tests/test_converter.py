from pathlib import Path

import pytest

from reg.platform.convert import ConversionError, DockerConverter

S = Path(__file__).parent / "fixtures" / "samples"


@pytest.mark.integration
def test_docker_converter_hwp_to_pdf():
    pdf = DockerConverter().to_pdf((S / "nst-yeobi-18.hwp").read_bytes(), "hwp")
    assert pdf.startswith(b"%PDF") and len(pdf) > 50_000


def test_missing_image_raises_conversion_error():
    with pytest.raises(ConversionError):
        DockerConverter(image="nst-regulation/does-not-exist:0", timeout=60).to_pdf(b"x", "hwp")
