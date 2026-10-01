"""시행일 판정 (spec 6.5): 부칙 > 개정 이력표 > ALIO 개정일 > 파일명."""
import re
from dataclasses import dataclass, field
from datetime import date

from reg.structure.model import ParsedDoc
from reg.structure.text import parse_dot_date

DATE_ANY = r"(\d{4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일|\d{4}\s*\.\s*\d{1,2}\s*\.\s*\d{1,2}\s*\.?)"
RE_PAREN = re.compile(r"날\s*[(（]\s*" + DATE_ANY + r"\s*[)）]\s*(?:로)?\s*부터")
RE_FROM = re.compile(DATE_ANY + r"\s*부터\s*시행")
RE_PUB = re.compile(r"(?:공포|결재|의결|통보|승인|시달|게시)[^.。]{0,40}?날\s*(?:로)?\s*부터\s*시행")
RE_BUT = re.compile(r"다만[,，]?\s*(.*?)(?:은|는)\s*" + DATE_ANY + r"\s*부터")
RE_ART = re.compile(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?")
RE_FILE = re.compile(r"(\d{4})\s*년(?:도)?\s*(\d{1,2})\s*월")


@dataclass
class Effective:
    effective_from: date | None
    basis: str
    status: str
    promulgated_on: date | None
    overrides: dict = field(default_factory=dict)


def _from_supplement(text: str, header: date | None) -> date | None:
    main = text.split("다만")[0]
    for rx in (RE_PAREN, RE_FROM):
        if m := rx.search(main):
            return parse_dot_date(m[1])
    if RE_PUB.search(main):
        return header
    return None


def resolve(doc: ParsedDoc, alio_date: date | None = None, filename: str = "") -> Effective:
    if doc.meta.get("effective_on"):
        return Effective(date.fromisoformat(doc.meta["effective_on"]), "api", "CONFIRMED",
                         date.fromisoformat(doc.meta["promulgated_on"]) if doc.meta.get("promulgated_on") else None)
    hist_last = doc.history[-1].date if doc.history else None
    supps = doc.supplements()
    dated = [(date.fromisoformat(s.meta["date"]) if s.meta.get("date") else None, i, s) for i, s in enumerate(supps)]
    last = max(dated, key=lambda x: (x[0] or date.min, x[1]))[2] if dated else None
    header = date.fromisoformat(last.meta["date"]) if last is not None and last.meta.get("date") else None
    text = " ".join([last.text] + [p.text for p in doc.provisions if p.parent == last.path]) if last else ""
    eff = _from_supplement(text, header) if last else None
    overrides = {}
    for m in RE_BUT.finditer(text):
        when = parse_dot_date(m[2])
        for a in RE_ART.finditer(m[1]):
            overrides[f"a{int(a[1])}" + (f"-{int(a[2])}" if a[2] else "")] = when
    promulgated = hist_last or header
    if eff is not None:
        conflict = (hist_last and header and hist_last != header) or (
            alio_date and alio_date not in {hist_last, eff})
        return Effective(eff, "supplement", "CONFLICT" if conflict else "CONFIRMED", promulgated, overrides)
    if hist_last:
        return Effective(hist_last, "history", "UNCERTAIN", promulgated, overrides)
    if alio_date:
        return Effective(alio_date, "alio", "UNCERTAIN", promulgated, overrides)
    if RE_FILE.search(filename or ""):
        return Effective(None, "filename", "UNCERTAIN", promulgated, overrides)
    return Effective(None, "none", "UNCERTAIN", promulgated, overrides)
