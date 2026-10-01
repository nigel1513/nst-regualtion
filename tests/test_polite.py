import httpx
import pytest
import respx

from reg.collect.polite import PoliteClient, StopCollecting


def make(**kw):
    slept, logs = [], []
    c = PoliteClient("t", min_interval=1.5, log=logs.append, sleep=slept.append, **kw)
    return c, slept, logs


@respx.mock
def test_waits_min_interval_between_requests():
    respx.get("https://x/a").respond(200, text="ok")
    c, slept, logs = make()
    c.get("https://x/a")
    c.get("https://x/a")
    assert len(slept) == 1 and 0 < slept[0] <= 1.5
    assert [l.status for l in logs] == [200, 200]


@respx.mock
def test_429_follows_retry_after_and_doubles_interval():
    route = respx.get("https://x/a")
    route.side_effect = [httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200, text="ok")]
    c, slept, _ = make()
    assert c.get("https://x/a").status_code == 200
    assert 7 in slept and c.min_interval == 3.0


@respx.mock
def test_403_stops_immediately():
    respx.get("https://x/a").respond(403)
    c, _, _ = make()
    with pytest.raises(StopCollecting):
        c.get("https://x/a")


@respx.mock
def test_three_bad_in_a_row_stops():
    respx.get("https://x/a").respond(503)
    c, _, _ = make()
    with pytest.raises(StopCollecting):
        c.get("https://x/a")


@respx.mock
def test_params_are_sent():
    route = respx.get("https://x/a", params={"q": "여비"}).respond(200)
    c, _, _ = make()
    c.get("https://x/a", params={"q": "여비"})
    assert route.called


@respx.mock
def test_backoff_is_capped_and_recovers_after_successes():
    route = respx.get("https://x/a")
    route.side_effect = ([httpx.Response(429, headers={"Retry-After": "1"}), httpx.Response(200)] * 6
                         + [httpx.Response(200)] * 20)
    c, _, _ = make()
    for _ in range(6):
        c.get("https://x/a")
    assert c.min_interval <= 30.0
    for _ in range(20):
        c.get("https://x/a")
    assert c.min_interval == 1.5
