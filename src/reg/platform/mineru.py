"""MinerU 4 V1 HTTP API 클라이언트 (GPU PC, infra/gpu-mineru). OCR(M6-5)과 별표 표 추출(M6-6)이 함께 쓴다.

주기: POST /v1/uploads → PUT 바이트 → POST /v1/uploads/{id}/complete → POST /v1/parse/jobs
      → GET /v1/parse/jobs/{id} 폴링(completed|partial|failed|canceled) → GET /v1/files/{file_id}/content
- API 키는 같은 출처(scheme+host+port) 요청에만 붙인다(저장소 SDK 규칙).
- 서버의 업로드·작업 상태는 프로세스 메모리에만 있다. 재시작으로 작업이 404가 되면 꺼짐과 같이 MineruUnavailable이다.
- 공개 이름(MineruClient, MineruResult, MineruError, MineruUnavailable, mineru_available, text_lines, table_rows)은
  M6-5·M6-6 공용 계약이다.
"""
import hashlib
import json
import time
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Self
from urllib.parse import urljoin, urlsplit

import httpx

TERMINAL = {"completed", "partial", "failed", "canceled"}
JOB_STATUSES = TERMINAL | {"queued", "running"}
FORMATS = ("markdown", "middle_json", "structured_content", "zip")
UNAVAILABLE_HTTP = {502, 503, 504}
HEALTH_TIMEOUT = 5.0


class MineruError(Exception):
    """요청·작업 실패: 4xx, 응답 형식 오류, 작업 failed/canceled/partial, 결과 없음, 폴링 시간 초과."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class MineruUnavailable(Exception):  # '오류'가 아니라 '지금 닿지 않음'
    """서비스에 닿지 않음: 연결 거부·시간 초과·502/503/504·재시작으로 작업 소실. 나중에 다시 하면 된다."""


@dataclass(frozen=True)
class MineruResult:
    job_id: str
    parser_version: str | None
    middle_json: dict | None = None
    markdown: str | None = None
    structured_content: dict | None = None
    zip: bytes | None = None


def _origin(url: str) -> tuple:
    p = urlsplit(url)
    return p.scheme.lower(), (p.hostname or "").lower(), p.port or (443 if p.scheme == "https" else 80)


def _str(d, key: str, where: str) -> str:
    v = d.get(key) if isinstance(d, dict) else None
    if not isinstance(v, str) or not v:
        raise MineruError(f"MinerU 응답 형식 오류 ({where}.{key})")
    return v


def _detail(r: httpx.Response) -> str:
    try:
        e = r.json().get("error") or {}
        return f"{e.get('code') or e.get('type') or ''}: {e.get('message') or ''}".strip(": ")
    except (ValueError, AttributeError):
        return r.text[:200]


def _job(d: dict) -> dict:
    _str(d, "job_id", "job")
    if d.get("status") not in JOB_STATUSES or not isinstance(d.get("files"), list):
        raise MineruError(f"MinerU 응답 형식 오류 (job.status={d.get('status')!r})")
    return d


class MineruClient:
    def __init__(self, base_url: str, api_key: str = "", timeout: float = 60.0, poll_interval: float = 3.0,
                 max_wait: float = 1800.0, transfer_timeout: float = 300.0):
        if not base_url:
            raise ValueError("MinerU 주소가 없다 (REG_MINERU_URL)")
        self.base = base_url.rstrip("/")
        self.api_key, self.timeout, self.transfer_timeout = api_key, timeout, transfer_timeout
        self.poll_interval, self.max_wait = poll_interval, max_wait
        self.http = httpx.Client(follow_redirects=False)

    @classmethod
    def from_settings(cls, s=None, **kw) -> "MineruClient":
        from reg.platform.settings import get_settings

        s = s or get_settings()
        return cls(s.mineru_url, s.mineru_api_key, **kw)

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ── 전송 ──────────────────────────────────────────────────────────
    def _request(self, method: str, path_or_url: str, *, timeout: float | None = None, headers: dict | None = None,
                 **kw) -> httpx.Response:
        url = urljoin(self.base + "/", path_or_url)
        h = dict(headers or {})
        if self.api_key and _origin(url) == _origin(self.base):
            h["Authorization"] = f"Bearer {self.api_key}"
        try:
            r = self.http.request(method, url, headers=h, timeout=timeout or self.timeout, **kw)
        except httpx.TransportError as e:
            raise MineruUnavailable(f"MinerU 연결 실패 ({method} {path_or_url}): {type(e).__name__}: {e}") from e
        if r.status_code in UNAVAILABLE_HTTP:
            raise MineruUnavailable(f"MinerU 일시 불가 ({method} {path_or_url}): HTTP {r.status_code} {_detail(r)}")
        if r.status_code >= 400:
            raise MineruError(f"MinerU 오류 ({method} {path_or_url}): HTTP {r.status_code} {_detail(r)}", r.status_code)
        return r

    def _json(self, method: str, path: str, **kw) -> dict:
        r = self._request(method, path, **kw)
        try:
            d = r.json()
        except ValueError as e:
            raise MineruError(f"MinerU 응답이 JSON이 아님 ({path})") from e
        if not isinstance(d, dict):
            raise MineruError(f"MinerU 응답 형식 오류 ({path})")
        return d

    # ── 상태 ──────────────────────────────────────────────────────────
    def health(self) -> dict:
        return self._json("GET", "/v1/health", timeout=min(self.timeout, HEALTH_TIMEOUT))

    def available(self, need: tuple[str, ...] = ("middle_json",)) -> bool:
        try:
            h = self.health()
        except (MineruError, MineruUnavailable):
            return False
        formats = (h.get("features") or {}).get("output_formats") or []
        return h.get("status") == "ok" and all(f in formats for f in need)

    # ── 주기 단계 ─────────────────────────────────────────────────────
    def upload(self, data: bytes, filename: str, mime_type: str = "application/pdf") -> str:
        sha = hashlib.sha256(data).hexdigest()
        up = self._json("POST", "/v1/uploads", json={"filename": filename, "bytes": len(data), "mime_type": mime_type,
                                                     "purpose": "parse", "sha256sum": sha})
        status = _str(up, "status", "upload")
        if status == "pending":
            if (up.get("upload_method") or "PUT") != "PUT":
                raise MineruError(f"MinerU 업로드 방식 미지원: {up.get('upload_method')}")
            self._request("PUT", _str(up, "upload_url", "upload"), content=data,
                          headers=dict(up.get("upload_headers") or {}), timeout=self.transfer_timeout)
            up = self._json("POST", f"/v1/uploads/{_str(up, 'id', 'upload')}/complete", json={"sha256sum": sha})
            status = _str(up, "status", "complete")
        if status != "completed":
            raise MineruError(f"MinerU 업로드 상태가 completed가 아님: {status}")
        return _str(up.get("file") or {}, "id", "upload.file")

    def submit(self, file_id: str, *, tier: str, ocr_mode: str, output_formats: tuple[str, ...],
               page_range: str | None = None) -> dict:
        entry: dict = {"source": {"type": "file_id", "file_id": file_id}}
        if page_range:
            entry["page_range"] = page_range
        return _job(self._json("POST", "/v1/parse/jobs", json={"files": [entry], "tier": tier, "ocr_mode": ocr_mode,
                                                               "output_formats": list(output_formats)}))

    def job(self, job_id: str) -> dict:
        try:
            return _job(self._json("GET", f"/v1/parse/jobs/{job_id}"))
        except MineruError as e:
            if e.status == 404:  # 서비스 재시작으로 작업 색인이 사라졌다
                raise MineruUnavailable(f"MinerU 작업 {job_id}이 사라짐 (서비스 재시작)") from e
            raise

    def wait(self, job: dict) -> dict:
        deadline = time.monotonic() + self.max_wait
        while job["status"] not in TERMINAL:
            if time.monotonic() >= deadline:
                raise MineruError(f"MinerU 작업 {job['job_id']} 대기 시간 초과 ({self.max_wait:.0f}초, {job['status']})")
            time.sleep(self.poll_interval)
            job = self.job(job["job_id"])
        return job

    def download(self, file_id: str) -> bytes:
        r = self._request("GET", f"/v1/files/{file_id}/content", timeout=self.transfer_timeout)
        if r.status_code in (301, 302, 303, 307, 308):  # 다른 출처로 가면 _request가 키를 붙이지 않는다
            r = self._request("GET", r.headers["location"], timeout=self.transfer_timeout)
        return r.content

    def parse(self, data: bytes, filename: str, *, tier: str = "standard", ocr_mode: str = "auto",
              output_formats: tuple[str, ...] = ("middle_json", "markdown"), page_range: str | None = None,
              mime_type: str = "application/pdf") -> MineruResult:
        bad = [f for f in output_formats if f not in FORMATS]
        if bad:
            raise ValueError(f"MinerU V1 API가 내지 않는 형식: {bad}")
        job = self.wait(self.submit(self.upload(data, filename, mime_type), tier=tier, ocr_mode=ocr_mode,
                                    output_formats=output_formats, page_range=page_range))
        f = job["files"][0] if job["files"] else {}
        if job["status"] != "completed" or f.get("status") != "completed":
            raise MineruError(f"MinerU 작업 {job['job_id']} {job['status']}: {f.get('error')}")
        outs = f.get("output_files") or {}
        got: dict[str, bytes] = {}
        for fmt in output_formats:
            ref = outs.get(fmt)
            if not ref:
                raise MineruError(f"MinerU 결과에 {fmt} 없음 (작업 {job['job_id']})")
            got[fmt] = self.download(_str(ref, "file_id", f"output_files.{fmt}"))

        def js(fmt: str) -> dict | None:
            if fmt not in got:
                return None
            try:
                return json.loads(got[fmt])
            except ValueError as e:
                raise MineruError(f"MinerU {fmt}가 JSON이 아님 (작업 {job['job_id']})") from e

        return MineruResult(job["job_id"], (f.get("parse") or {}).get("parser_version"), js("middle_json"),
                            got["markdown"].decode("utf-8") if "markdown" in got else None,
                            js("structured_content"), got.get("zip"))


def mineru_available(base_url: str, api_key: str = "", timeout: float = HEALTH_TIMEOUT) -> bool:
    """값싼 상태 확인: GET /v1/health가 ok이고 middle_json을 낼 수 있으면 True. 주소가 없으면 False."""
    if not base_url:
        return False
    with MineruClient(base_url, api_key, timeout=timeout) as c:
        return c.available()


# ── middle_json(MiddleJson 2.0) → 읽는 순서의 줄 ───────────────────────────
SKIP_BLOCKS = {"header", "footer", "page_number", "aside_text"}  # 쪽 장식: 본문에 섞지 않는다
NON_TEXT_BODIES = {"image_body", "chart_body", "equation", "code_body", "algorithm_body"}
INLINE_SPANS = {"text", "equation_inline", "code_inline", "hyperlink"}


def _norm(s: str) -> str:
    return " ".join(unicodedata.normalize("NFC", s).split())


def _spans(spans: list) -> str:
    out = []
    for s in spans:
        c = s.get("content")
        out.append(_spans(c) if isinstance(c, list) else (c or ""))
    return "".join(out)


class _Rows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows: list[list[str]] = []
        self.row: list[str] | None = None
        self.cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []
        elif tag == "br" and self.cell is not None:
            self.cell.append(" ")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append(_norm("".join(self.cell)))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)


def table_rows(html: str) -> list[str]:
    """table_body → 행마다 '칸 | 칸'. HTML이 아니면(공간 투영 텍스트) 줄 그대로. 빈 행은 뺀다."""
    p = _Rows()
    p.feed(html)
    p.close()
    if not p.rows:
        return [n for ln in html.splitlines() if (n := _norm(ln))]
    return [" | ".join(r) for r in p.rows if any(r)]


def _block_lines(block: dict) -> list[str]:
    t, c = block.get("type"), block.get("content")
    if t in SKIP_BLOCKS or t in NON_TEXT_BODIES:
        return []
    if t == "table_body" and isinstance(c, str):
        return table_rows(c)
    if isinstance(c, str):
        raw = c
    elif isinstance(c, list) and all(isinstance(x, dict) and x.get("type") in INLINE_SPANS for x in c):
        raw = _spans(c)
    elif isinstance(c, list):  # 부모 블록(table·list·index·image…): 자식 블록을 차례로
        return [ln for child in c if isinstance(child, dict) for ln in _block_lines(child)]
    else:
        return []
    return [n for ln in raw.splitlines() if (n := _norm(ln))]


def _scale(b, size: tuple[float, float] | None) -> list[float] | None:
    if not size or not isinstance(b, list | tuple) or len(b) != 4:
        return None
    w, h = size
    return [round(b[0] * w, 1), round(b[1] * h, 1), round(b[2] * w, 1), round(b[3] * h, 1)]


def text_lines(middle_json: dict, page_sizes: dict[int, tuple[float, float]]) -> list[dict]:
    """MiddleJson 2.0 → [{text, page(1부터), bbox(원본 PDF pt, 왼쪽 위 원점) | None}] 읽는 순서.

    - 머리글·꼬리글·쪽번호·여백 글은 뺀다.
    - 문단 안 줄바꿈은 줄로 나누되 같은 문단 상자를 준다.
    - 표는 행마다 한 줄이다. 그림·수식 본문은 뺀다.
    - 쪽 크기를 모르면 bbox는 None이다(지어내지 않는다).
    """
    out = []
    for page in middle_json.get("pages") or []:
        idx = int(page.get("page_idx", 0))
        size = page_sizes.get(idx)
        for block in sorted(page.get("blocks") or [], key=lambda b: b.get("index", 0)):
            if block.get("type") in SKIP_BLOCKS:
                continue
            bbox = _scale(block.get("bbox"), size)
            out.extend({"text": ln, "page": idx + 1, "bbox": bbox} for ln in _block_lines(block))
    return out
