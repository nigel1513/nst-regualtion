"""출처 규칙을 강제하는 HTTP 클라이언트 (world_law_collect/wlc/polite.py 이식).

- 출처당 요청 1개씩, 응답 완료 시점 기준 최소 간격 보장
- 429/503: Retry-After를 따르고 간격을 두 배로
- 403, 3xx, 5xx(503 제외): 즉시 중지 / 나쁜 응답 연속 max_bad회: 중지
"""
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from reg.settings import USER_AGENT

MAX_INTERVAL = 30.0  # 429/503 뒤 늘린 간격의 상한 (초)
RECOVER_AFTER = 20  # 연속 성공이 이만큼이면 기본 간격으로 되돌린다


class StopCollecting(Exception):
    """차단 위험 신호. 수집을 즉시 멈춰야 한다."""


@dataclass
class RequestLog:
    source: str
    url: str
    status: int | None
    bytes: int | None
    elapsed_ms: int
    waited_ms: int
    error: str | None = None


class PoliteClient:
    def __init__(self, source: str, min_interval: float, log: Callable[[RequestLog], None] | None = None,
                 max_bad: int = 3, timeout: float = 60.0, sleep: Callable[[float], None] = time.sleep):
        self.source = source
        self.min_interval = min_interval
        self.base_interval = min_interval
        self.ok_streak = 0
        self.max_bad = max_bad
        self.bad_streak = 0
        self._log = log or (lambda _: None)
        self._sleep = sleep
        self._last_done: float | None = None
        self.client = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=timeout,
                                   follow_redirects=False)

    def get(self, url: str, params: dict | None = None) -> httpx.Response:
        waited = 0.0
        if self._last_done is not None:
            waited = self.min_interval - (time.monotonic() - self._last_done)
            if waited > 0:
                self._sleep(waited)
            waited = max(waited, 0.0)
        t0 = time.monotonic()
        try:
            resp = self.client.get(url, params=params)
        except httpx.HTTPError as e:
            self._last_done = time.monotonic()
            self._log(RequestLog(self.source, url, None, None, int((self._last_done - t0) * 1000),
                                 int(waited * 1000), repr(e)))
            self._bad(f"네트워크 오류 {e!r}")
            raise
        self._last_done = time.monotonic()
        self._log(RequestLog(self.source, str(resp.request.url), resp.status_code, len(resp.content),
                             int((self._last_done - t0) * 1000), int(waited * 1000)))

        if resp.status_code in (429, 503):
            self._bad(f"HTTP {resp.status_code}")
            retry = resp.headers.get("Retry-After", "")
            self._sleep(min(float(retry) if retry.isdigit() else 60.0, 600.0))
            self.min_interval = min(self.min_interval * 2, max(MAX_INTERVAL, self.base_interval))
            self.ok_streak = 0
            return self.get(url, params)
        if resp.status_code == 403 or resp.status_code >= 500 or 300 <= resp.status_code < 400:
            raise StopCollecting(f"{self.source}: HTTP {resp.status_code} — 차단 위험 신호로 중지")
        self.bad_streak = 0
        self.ok_streak += 1
        if self.ok_streak >= RECOVER_AFTER:
            self.min_interval = self.base_interval
        return resp

    def _bad(self, why: str) -> None:
        self.bad_streak += 1
        if self.bad_streak >= self.max_bad:
            raise StopCollecting(f"{self.source}: {why} 연속 {self.bad_streak}회 — 중지")

    def close(self) -> None:
        self.client.close()
