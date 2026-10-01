"""ALIO 내부규정 공시 클라이언트 (엔드포인트 2026-10-01 확인)."""
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date

from reg.collect.polite import PoliteClient

_BFILE_SPLIT = re.compile(r",(?=\d+\|)")


class AlioError(Exception):
    """ALIO가 정상 JSON을 주지 않음 (점검, 오류 페이지 등)."""


def parse_bfiles(s: str | None) -> list[tuple[str, str]]:
    if not s:
        return []
    out = []
    for part in _BFILE_SPLIT.split(s):
        no, _, name = part.partition("|")
        if no.strip() and name:
            out.append((no.strip(), name))
    return out


def _date(s: str | None) -> date | None:
    m = re.match(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", s or "")
    return date(int(m[1]), int(m[2]), int(m[3])) if m else None


@dataclass
class ListRow:
    seq: str
    title: str
    apba_id: str
    divis: str | None
    fingerprint: str


@dataclass
class RuleDetail:
    seq: str
    title: str
    divis: str | None
    revised_on: date | None
    posted_on: date | None
    files: list[tuple[str, str]]
    raw: dict = field(repr=False)


class AlioClient:
    def __init__(self, http: PoliteClient, base: str = "https://www.alio.go.kr"):
        self.http = http
        self.base = base

    def _json(self, path: str, params: dict) -> dict:
        resp = self.http.get(self.base + path, params=params)
        try:
            body = resp.json()
        except ValueError as e:
            raise AlioError(f"{path}: JSON 아님 ({resp.text[:80]!r})") from e
        if body.get("status") != "success":
            raise AlioError(f"{path}: status={body.get('status')} message={body.get('message')}")
        return body["data"]

    def list_rules(self, alio_name: str, apba_id: str) -> Iterator[ListRow]:
        page = 1
        while True:
            data = self._json("/occasional/findRuleList.json",
                              {"type": "apbaNa", "word": alio_name, "pageNo": page})
            for r in data["result"]:
                if r.get("apbaId") != apba_id:
                    continue
                yield ListRow(str(r["seq"]), r["title"].strip(), r["apbaId"], r.get("insdRuleDivis"),
                              "|".join(str(r.get(k)) for k in ("submissionNo", "ruleStDa", "idate", "crctYn", "reSbmtYn")))
            if page >= int(data["page"]["totalPage"]):
                return
            page += 1

    def detail(self, seq: str) -> RuleDetail:
        d = self._json("/occasional/findRuleDtl.json", {"seq": seq})
        return RuleDetail(seq, d["title"].strip(), d.get("insdRuleDivis"), _date(d.get("retryRvsnYmd")),
                          _date(d.get("idate")), parse_bfiles(d.get("bFiles")), d)

    def download(self, file_no: str) -> bytes:
        return self.http.get(self.base + "/download/rulefiledown.json", params={"fileNo": file_no}).content
