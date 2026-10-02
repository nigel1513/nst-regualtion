"""OpenSearch 보안 플러그인(사용자 결정 2026-10-02): 주소의 계정(http://user:pw@host)을 Basic 인증으로 보낸다."""
import base64

import httpx
import respx

from reg.index.os import OpenSearch


@respx.mock
def test_credentials_in_url_become_basic_auth_and_leave_the_url():
    route = respx.get("http://os.local:9200/_cluster/health").mock(return_value=httpx.Response(200, json={"status": "green"}))
    OpenSearch("http://reg_app:p%40ss@os.local:9200").c.get("/_cluster/health")
    req = route.calls[0].request
    assert req.headers["Authorization"] == "Basic " + base64.b64encode(b"reg_app:p@ss").decode()
    assert req.url.host == "os.local" and not req.url.username


@respx.mock
def test_no_credentials_means_no_auth_header():
    route = respx.get("http://os.local:9200/").mock(return_value=httpx.Response(200, json={}))
    OpenSearch("http://os.local:9200").c.get("/")
    assert "Authorization" not in route.calls[0].request.headers
