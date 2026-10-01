"""보기용 PDF 줄에서 조항 위치 찾기 (공백 무시, 문서 순서대로 전진 검색)."""
import re

from reg.structure.model import Block, ParsedDoc, Prov

_WS = re.compile(r"\s+")
UNITS = {"chapter", "article", "paragraph", "item", "supplement", "annex"}


def _n(s: str) -> str:
    return _WS.sub("", s or "")


def _key(p: Prov) -> str | None:
    if p.unit == "chapter":
        return _n(p.label)
    if p.unit == "article":
        return _n(p.label + (f"({p.heading}" if p.heading else ""))[:12]
    if p.unit in ("paragraph", "item"):
        return _n(p.label + p.text)[:10]
    if p.unit == "supplement":
        return "부칙"
    if p.unit == "annex":
        return _n(p.label)
    return None


def locate(doc: ParsedDoc, blocks: list[Block]) -> int:
    lines = [_n(b.text) for b in blocks]
    pos, n = 0, 0
    for p in doc.provisions:
        if p.unit not in UNITS or p.anchor:
            continue
        key = _key(p)
        if not key:
            continue
        for i in range(pos, len(lines)):
            if lines[i].startswith(key) or (p.unit in ("paragraph", "item") and key in lines[i]):
                b = blocks[i]
                p.anchor = {"page": b.page, "bbox": list(b.bbox) if b.bbox else None}
                pos, n = i, n + 1
                break
    return n
