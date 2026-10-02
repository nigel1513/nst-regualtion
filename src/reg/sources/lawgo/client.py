"""국가법령정보 공동활용 Open API (DRF) 클라이언트."""
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date

from reg.platform.http import PoliteClient

_DOTS = re.compile(r"[\s·ㆍ‧∙・]")


def norm_name(s: str) -> str:
    return _DOTS.sub("", s or "")


def _ymd(s: str | None) -> date | None:
    return date(int(s[:4]), int(s[4:6]), int(s[6:8])) if s and len(s) == 8 and s.isdigit() else None


@dataclass
class LawSummary:
    mst: str
    law_id: str
    name: str
    kind: str
    promulgated_on: date | None
    effective_on: date | None
    status: str


def parse_search(xml: bytes) -> list[LawSummary]:
    root = ET.fromstring(xml)
    return [LawSummary(e.findtext("법령일련번호", "").strip(), e.findtext("법령ID", "").strip(),
                       (e.findtext("법령명한글") or "").strip(), (e.findtext("법령구분명") or "").strip(),
                       _ymd(e.findtext("공포일자")), _ymd(e.findtext("시행일자")),
                       (e.findtext("현행연혁코드") or "").strip())
            for e in root.findall("law")]


class LawGoClient:
    def __init__(self, http: PoliteClient, oc: str, base: str = "https://www.law.go.kr"):
        self.http, self.oc, self.base = http, oc, base

    def search(self, query: str) -> list[LawSummary]:
        r = self.http.get(f"{self.base}/DRF/lawSearch.do", params={
            "OC": self.oc, "target": "law", "type": "XML", "display": 100, "query": query})
        return parse_search(r.content)

    def fetch(self, mst: str) -> bytes:
        return self.http.get(f"{self.base}/DRF/lawService.do", params={
            "OC": self.oc, "target": "law", "MST": mst, "type": "XML"}).content
