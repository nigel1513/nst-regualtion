"""V1 전체 주기를 respx 가짜로 돈다. 응답 모양은 tests/ocr/mineru_fake.py 머리말의 저장소 계약 기반이다(녹화 아님)."""
import hashlib
import json

import httpx
import pytest
import respx

from reg.platform.mineru import MineruClient, MineruError, MineruUnavailable, mineru_available
from tests.ocr.mineru_fake import BASE, HEALTH, KEY, MARKDOWN, MIDDLE, job, mock_cycle, upload_pending

PDF = b"%PDF-1.4 fake"


def _client(**kw) -> MineruClient:
    return MineruClient(BASE, KEY, poll_interval=0, **kw)


def test_full_cycle_returns_requested_outputs():
    with respx.mock(assert_all_called=False) as m:
        r = mock_cycle(m, PDF)
        res = _client().parse(PDF, "source.pdf", tier="standard", ocr_mode="ocr")
    assert res.job_id == "job_1" and res.parser_version == "4.0.0"
    assert res.middle_json == MIDDLE and res.markdown == MARKDOWN
    assert res.structured_content is None and res.zip is None
    body = json.loads(r["submit"].calls[0].request.content)
    assert body == {"files": [{"source": {"type": "file_id", "file_id": "file_1"}}], "tier": "standard",
                    "ocr_mode": "ocr", "output_formats": ["middle_json", "markdown"]}
    assert r["put"].calls[0].request.content == PDF
    assert r["put"].calls[0].request.headers["authorization"] == f"Bearer {KEY}"  # 같은 출처: 키를 붙인다
    assert json.loads(r["create"].calls[0].request.content)["sha256sum"] == hashlib.sha256(PDF).hexdigest()
    assert r["poll"].call_count == 2


def test_deduplicated_upload_skips_byte_upload():
    with respx.mock(assert_all_called=False) as m:
        r = mock_cycle(m, PDF, dedup=True)
        _client().parse(PDF, "source.pdf")
    assert r["put"].call_count == 0 and r["complete"].call_count == 0


def test_cross_origin_upload_url_does_not_get_the_key():
    with respx.mock(assert_all_called=False) as m:
        r = mock_cycle(m, PDF)
        r["create"].return_value = httpx.Response(
            200, json=upload_pending(len(PDF), hashlib.sha256(PDF).hexdigest(), url="http://storage.test/put/1"))
        put = m.put("http://storage.test/put/1").respond(200)
        _client().parse(PDF, "source.pdf")
    assert "authorization" not in put.calls[0].request.headers


@pytest.mark.parametrize("final", ["failed", "canceled", "partial"])
def test_non_completed_job_is_an_error(final):
    with respx.mock(assert_all_called=False) as m:
        mock_cycle(m, PDF, final=final)
        with pytest.raises(MineruError, match=final):
            _client().parse(PDF, "source.pdf")


def test_missing_requested_output_is_an_error():
    with respx.mock(assert_all_called=False) as m:
        r = mock_cycle(m, PDF)
        r["poll"].side_effect = None
        r["poll"].return_value = httpx.Response(
            200, json=job("completed", outputs={"markdown": {"file_id": "file_md", "bytes": 1}}))
        with pytest.raises(MineruError, match="middle_json"):
            _client().parse(PDF, "source.pdf")


def test_poll_budget_exhausted_is_an_error_not_unavailable():
    with respx.mock(assert_all_called=False) as m:
        mock_cycle(m, PDF)
        with pytest.raises(MineruError, match="대기 시간 초과"):
            _client(max_wait=0).parse(PDF, "source.pdf")


def test_connection_refused_is_unavailable():
    with respx.mock() as m:
        m.post(f"{BASE}/v1/uploads").mock(side_effect=httpx.ConnectError("refused"))
        with pytest.raises(MineruUnavailable, match="연결 실패"):
            _client().parse(PDF, "source.pdf")


def test_read_timeout_is_unavailable():
    with respx.mock() as m:
        m.post(f"{BASE}/v1/uploads").mock(side_effect=httpx.ReadTimeout("slow"))
        with pytest.raises(MineruUnavailable):
            _client().parse(PDF, "source.pdf")


@pytest.mark.parametrize("code", [502, 503, 504])
def test_gateway_and_preload_errors_are_unavailable(code):
    with respx.mock() as m:
        m.post(f"{BASE}/v1/uploads").respond(code, json={"error": {"type": "engine_error", "message": "loading"}})
        with pytest.raises(MineruUnavailable):
            _client().parse(PDF, "source.pdf")


def test_job_lost_after_restart_is_unavailable():
    with respx.mock(assert_all_called=False) as m:
        r = mock_cycle(m, PDF)
        r["poll"].side_effect = None
        r["poll"].return_value = httpx.Response(
            404, json={"error": {"type": "invalid_request_error", "code": "job_not_found", "message": "no job"}})
        with pytest.raises(MineruUnavailable, match="사라짐"):
            _client().parse(PDF, "source.pdf")


def test_client_error_carries_status_and_message():
    with respx.mock() as m:
        m.post(f"{BASE}/v1/uploads").respond(
            401, json={"error": {"type": "authentication_error", "code": "invalid_api_key", "message": "bad key"}})
        with pytest.raises(MineruError, match="bad key") as e:
            _client().parse(PDF, "source.pdf")
    assert e.value.status == 401


def test_malformed_job_response_is_an_error():
    with respx.mock(assert_all_called=False) as m:
        r = mock_cycle(m, PDF)
        r["submit"].return_value = httpx.Response(200, json={"job_id": None, "status": "queued"})
        with pytest.raises(MineruError, match="형식"):
            _client().parse(PDF, "source.pdf")


def test_available_and_health():
    with respx.mock() as m:
        m.get(f"{BASE}/v1/health").respond(json=HEALTH)
        assert mineru_available(BASE, KEY) is True
        assert _client().available(need=("middle_json", "markdown")) is True
        assert _client().available(need=("docx",)) is False
    with respx.mock() as m:
        m.get(f"{BASE}/v1/health").mock(side_effect=httpx.ConnectError("down"))
        assert mineru_available(BASE, KEY) is False
    with respx.mock() as m:
        m.get(f"{BASE}/v1/health").respond(503, json={"error": {"type": "engine_error", "message": "preload"}})
        assert mineru_available(BASE, KEY) is False
    assert mineru_available("", KEY) is False


def test_from_settings_requires_url():
    from reg.platform.settings import Settings

    with pytest.raises(ValueError, match="REG_MINERU_URL"):
        MineruClient.from_settings(Settings(mineru_url=""))
    c = MineruClient.from_settings(Settings(mineru_url=BASE + "/", mineru_api_key=KEY), poll_interval=1)
    assert c.base == BASE and c.poll_interval == 1
