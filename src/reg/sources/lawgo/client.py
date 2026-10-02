"""law.go.kr DRF 호출만 맡는다 (spec §3A.4). 해석은 xml.py, 적재는 mirror.py가 한다.

- OC 키는 요청 때만 붙인다. 요청 로그에는 OC=***로 가린다.
- law.go.kr는 키 미승인·검증 실패·없는 본문에도 HTTP 200을 준다. 그래서 본문을 보고 오류를 판별한다.
"""
import re
import time
from collections.abc import Callable

from reg.platform.http import PoliteClient, RequestLog
from reg.sources.lawgo.errors import KeyNotApproved, KeyRejected, LawGoError, NotFound, ResponseChanged

BASE = "https://www.law.go.kr"
DRF = f"{BASE}/DRF"
LIST_TARGETS = ("law", "admrul", "licbyl", "admbyl")
SORTABLE = ("law", "admrul")  # licbyl·admbyl은 sort를 무시한다 (2026-10-02 확인)
MIN_INTERVAL = 1.0
_OC = re.compile(r"([?&]OC=)[^&\s'\"]*")
_UNAPPROVED = "미신청된 목록/본문".encode()
_NO_MATCH = "일치하는".encode()


def redact(s: str | None) -> str | None:
    return _OC.sub(r"\1***", s) if s else s


def redacting(log: Callable[[RequestLog], None] | None) -> Callable[[RequestLog], None]:
    def inner(r: RequestLog) -> None:
        if log is not None:
            log(RequestLog(r.source, redact(r.url), r.status, r.bytes, r.elapsed_ms, r.waited_ms, redact(r.error)))
    return inner


def _tag(data: bytes, tag: bytes) -> str:
    m = re.search(rb"<" + tag + rb">\s*([^<]*?)\s*</" + tag + rb">", data)
    return m[1].decode("utf-8", "replace") if m else ""


def check(data: bytes, what: str, *, html: bool = False) -> bytes:
    head = data[:600]
    if _UNAPPROVED in data:
        raise KeyNotApproved(
            f"law.go.kr: OC 키가 '{what}'에 대해 승인되지 않았습니다(미신청된 목록/본문에 대한 접근)."
            " open.law.go.kr [OPEN API 신청]에서 해당 API와 법령종류의 승인 상태를 확인하세요")
    if re.search(rb"<Response>\s*<result>", head):
        raise KeyRejected(f"law.go.kr가 '{what}' 요청을 거부했습니다: {_tag(data, b'result')} {_tag(data, b'msg')}")
    if re.search(rb"<Law>\s*" + _NO_MATCH, head):
        raise NotFound(f"law.go.kr: '{what}'에 해당하는 본문이 없습니다")
    if not html and not data.lstrip().startswith(b"<?xml"):
        raise ResponseChanged(f"law.go.kr '{what}': XML이 아닌 응답 (앞부분 {data.lstrip()[:60]!r})")
    return data


class LawGoClient:
    def __init__(self, http: PoliteClient, oc: str):
        if not oc:
            raise LawGoError("REG_LAWGO_OC가 비어 있습니다. .env에 운영 OC 키를 넣으세요(표본 수집·개발은 test)")
        self.http, self.oc = http, oc

    def search(self, target: str, *, page: int = 1, display: int = 100, sort: str | None = None,
               query: str | None = None, search: int | None = None) -> bytes:
        if target not in LIST_TARGETS:
            raise ValueError(f"목록 target이 아님: {target}")
        p: dict = {"OC": self.oc, "target": target, "type": "XML", "page": page, "display": display}
        if sort and target in SORTABLE:
            p["sort"] = sort
        if query:
            p["query"] = query
        if search:
            p["search"] = search
        return check(self.http.get(f"{DRF}/lawSearch.do", params=p).content, f"{target} 목록 {page}쪽")

    def service(self, target: str, key: str) -> bytes:
        if target not in ("law", "admrul"):
            raise ValueError(f"본문 target이 아님: {target}")
        p = {"OC": self.oc, "target": target, "type": "XML", ("MST" if target == "law" else "ID"): key}
        return check(self.http.get(f"{DRF}/lawService.do", params=p).content, f"{target} 본문 {key}")

    def annex_html(self, target: str, seq: str) -> bytes:
        if target not in ("licbyl", "admbyl"):
            raise ValueError(f"별표 target이 아님: {target}")
        p = {"OC": self.oc, "target": target, "ID": seq, "type": "HTML"}
        return check(self.http.get(f"{DRF}/lawService.do", params=p).content, f"{target} 별표 {seq}", html=True)

    def file(self, path: str) -> bytes:
        """목록의 별표서식(PDF)파일링크. OC가 필요 없는 law.go.kr 공개 내려받기."""
        if not path.startswith("/LSW/flDownload.do?"):
            raise ValueError(f"별표 파일 경로가 아님: {path}")
        return self.http.get(f"{BASE}{path}").content

    def close(self) -> None:
        self.http.close()


def make_client(oc: str, min_interval: float = MIN_INTERVAL, log: Callable[[RequestLog], None] | None = None,
                sleep: Callable[[float], None] = time.sleep) -> LawGoClient:
    if not oc:
        raise LawGoError("REG_LAWGO_OC가 비어 있습니다. .env에 운영 OC 키를 넣으세요(표본 수집·개발은 test)")
    http = PoliteClient("lawgo", max(min_interval, MIN_INTERVAL), log=redacting(log), sleep=sleep)
    return LawGoClient(http, oc)
