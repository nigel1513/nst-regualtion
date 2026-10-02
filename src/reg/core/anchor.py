# src/reg/core/anchor.py
"""보기용 PDF 줄에서 조항 위치 찾기 (공백 무시, 문서 순서대로 전진 검색).

별표·별지는 머리 줄 모양이 원문마다 달라('[별지 제 1 호]', '<별표 1>', '별지 제4호 서식') 라벨 글자 대신
(종류, 번호, 가지번호)로 맞춘다 (M6-6: HWP 별표 위치 0.6% → 약 99%).
"""
import re

from reg.core.model import Block, ParsedDoc, Prov
from reg.core.parse import annex_heading
from reg.core.text import normalize_glyphs

_WS = re.compile(r"\s+")
_ANNEX_PATH = re.compile(r"^(annex|form)(\d+)(?:-(\d+))?")
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
    return None


def _annex_sig(p: Prov) -> tuple | None:
    m = _ANNEX_PATH.match(p.path)
    return (m[1], int(m[2]), int(m[3]) if m[3] else None) if m else None


def locate(doc: ParsedDoc, blocks: list[Block]) -> int:
    lines = [_n(normalize_glyphs(b.text)) for b in blocks]  # 파서가 정리한 글리프와 같은 글자로 비교한다
    sigs: dict[int, tuple | None] = {}
    pos, n = 0, 0
    for p in doc.provisions:
        if p.unit not in UNITS or p.anchor:
            continue
        hit = None
        if p.unit == "annex":
            want = _annex_sig(p)
            for i in range(pos, len(blocks)):
                if i not in sigs:
                    h = annex_heading(blocks[i].text)
                    sigs[i] = h[:3] if h else None
                if want and sigs[i] == want:
                    hit = i
                    break
        else:
            key = _key(p)
            if not key:
                continue
            for i in range(pos, len(lines)):
                if lines[i].startswith(key) or (p.unit in ("paragraph", "item") and key in lines[i]):
                    hit = i
                    break
        if hit is not None:
            b = blocks[hit]
            p.anchor = {"page": b.page, "bbox": list(b.bbox) if b.bbox else None}
            pos, n = hit, n + 1
    return n
