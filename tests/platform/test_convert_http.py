from pathlib import Path

import httpx
import pytest
import respx

from reg.platform import convert
from reg.platform.convert import ConversionError, DockerConverter, HttpConverter, get_converter
from reg.platform.settings import Settings

URL = "http://converter:8080"


@respx.mock
def test_posts_bytes_and_returns_pdf():
    route = respx.post(f"{URL}/convert", params={"kind": "hwp"}).mock(
        return_value=httpx.Response(200, content=b"%PDF-1.7 x"))
    assert HttpConverter(URL).to_pdf(b"HWP", "hwp") == b"%PDF-1.7 x"
    assert route.calls.last.request.content == b"HWP"
    assert route.calls.last.request.headers["content-type"] == "application/octet-stream"


@respx.mock
def test_http_error_becomes_conversion_error():
    respx.post(f"{URL}/convert").mock(return_value=httpx.Response(422, text="rc=1 깨진 파일"))
    with pytest.raises(ConversionError, match="HTTP 422.*깨진 파일"):
        HttpConverter(URL).to_pdf(b"x", "hwpx")


@respx.mock
def test_non_pdf_body_is_rejected():
    respx.post(f"{URL}/convert").mock(return_value=httpx.Response(200, content=b"<html>"))
    with pytest.raises(ConversionError, match="PDF가 아님"):
        HttpConverter(URL).to_pdf(b"x", "hwp")


@respx.mock
def test_connect_errors_are_retried_then_succeed():
    respx.post(f"{URL}/convert").mock(side_effect=[httpx.ConnectError("refused"),
                                                   httpx.Response(200, content=b"%PDF ok")])
    assert HttpConverter(URL, wait=0).to_pdf(b"x", "hwp") == b"%PDF ok"


@respx.mock
def test_converter_down_is_conversion_error_not_crash():
    respx.post(f"{URL}/convert").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(ConversionError, match="연결할 수 없음"):
        HttpConverter(URL, tries=2, wait=0).to_pdf(b"x", "hwp")


@respx.mock
def test_read_timeout_is_conversion_error():
    respx.post(f"{URL}/convert").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(ConversionError, match="호출 실패"):
        HttpConverter(URL).to_pdf(b"x", "hwp")


def test_unsupported_kind_fails_without_request():
    with respx.mock(assert_all_called=False) as m:
        route = m.post(f"{URL}/convert")
        with pytest.raises(ConversionError, match="형식"):
            HttpConverter(URL).to_pdf(b"x", "pdf")
        assert not route.called


def test_get_converter_selects_by_settings():
    assert isinstance(get_converter(Settings(converter_url=URL)), HttpConverter)
    assert get_converter(Settings(converter_url=URL)).base_url == URL
    assert isinstance(get_converter(Settings(converter_url="")), DockerConverter)
    assert DockerConverter().image == "nst-regulation/converter:0.2"


def test_only_platform_constructs_docker_converter():
    src = Path(convert.__file__).resolve().parents[1]   # src/reg
    offenders = [str(p) for p in src.rglob("*.py")
                 if p.name != "convert.py" and "DockerConverter(" in p.read_text(encoding="utf-8")]
    assert offenders == [], "변환기는 get_converter()로 만든다"
