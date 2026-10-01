"""내부규정 공통 구조 파서: Block 줄/문단 → ParsedDoc.

머리부(제목·원규분류·개정 이력·목차) → 본문(장·절·조·항·호·목) → 부칙 → 별표·별지 순서로 읽는다.
본문 시작 = 제목 괄호가 있는 첫 조문(목차 줄은 괄호가 없다), 그 앞의 가장 가까운 '제1장'이 있으면 거기부터.
"""
import re

from reg.structure.model import Block, HistEntry, ParsedDoc, Prov
from reg.structure.text import Joiner, clean, parse_dot_date, split_notes

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
RE_CHAPTER = re.compile(r"^제\s*(\d+)\s*장\s*(.{0,30})$")
RE_SECTION = re.compile(r"^제\s*(\d+)\s*절\s*(.{0,30})$")
RE_ARTICLE = re.compile(r"^제\s*(\d+)\s*조(?:\s*의\s*(\d+))?\s*(?:\(\s*([^()]{1,40}?)\s*\))?\s*(.*)$")
RE_SUPPL = re.compile(r"^부\s*칙\s*(?:[<〈(](.*?)[>〉)])?\s*(.*)$")
RE_ANNEX = re.compile(r"^[<\[〈]?\s*(별\s*표|별\s*지)\s*(?:제\s*)?(\d+)\s*(?:호)?(?:\s*의\s*(\d+))?\s*(?:서식)?\s*[>\]〉]?\s*(.*)$")
RE_ITEM = re.compile(r"^(\d{1,3})(?:\s*의\s*(\d+))?\.(?!\d)\s*(.*)$")  # 날짜(2024. 3. 1.)·소수(3.5)는 호가 아니다
RE_SUB = re.compile(r"^([가-하])\.\s*(.*)$")
RE_HIST = re.compile(r"^(제\s*정|전\s*부\s*개\s*정|일\s*부\s*개\s*정|개\s*정|폐\s*지)\s*"
                     r"(\d{4}\s*\.\s*\d{1,2}\s*\.\s*\d{1,2})\s*\.?\s*(?:(?:규|훈령|예규|규정)?\s*제?\s*(\d+)\s*호)?")
RE_CLASS = re.compile(r"원규\s*분류\s*(?:기\s*호)?\s*[:：]\s*([^)）]+?)\s*[)）]?\s*$")
RE_LEADER = re.compile(r"[·.…]{2,}|·\s*·|^[·\s]+$|\s·$")
PARTICLE = re.compile(r"^(?:에서|에|의|을|를|과|와|및|으로|로)(?:\s|$)")
RE_LAWNO = re.compile(r"^[<(〈]?\s*제\s*\d+\s*호")
INLINE_PARA = re.compile(r"(?<=[.。>\]」)])\s*(?=[①-⑳])")


def _article_key(no: str, sub: str | None) -> str:
    return f"a{int(no)}" + (f"-{int(sub)}" if sub else "")


def _num(no: str, sub: str | None) -> tuple[int, int]:
    return int(no), int(sub or 0)


def _despace_title(s: str) -> str:
    toks = s.split()
    return "".join(toks) if toks and all(len(t) == 1 for t in toks) else s


class _Builder:
    def __init__(self, joiner: Joiner):
        self.j = joiner
        self.provs: list[Prov] = []
        self.chapter: str | None = None
        self.section: str | None = None
        self.article: Prov | None = None
        self.para: Prov | None = None
        self.item: Prov | None = None
        self.cur: Prov | None = None
        self.last_art = (0, 0)
        self.last_chapter = 0
        self.supp: Prov | None = None
        self.supp_dates: dict[str, int] = {}
        self.unparsed = 0

    def add(self, p: Prov, b: Block) -> Prov:
        if b.page is not None:
            p.anchor = {"page": b.page, "bbox": list(b.bbox) if b.bbox else None}
        self.provs.append(p)
        self.cur = p
        return p

    def append_text(self, text: str) -> None:
        if self.cur is None:
            self.unparsed += 1
            return
        self.cur.text = self.j.join(self.cur.text, text) if self.cur.text else text

    def scope(self) -> str | None:
        return self.supp.path if self.supp else None


def _finish(p: Prov) -> None:
    text, notes = split_notes(p.text)
    p.text, p.annotations = text, p.annotations + notes
    if re.fullmatch(r"삭\s*제\s*\.?", text or "") or (p.deleted and not text):
        p.deleted, p.text = True, "삭제"


def _header(blocks: list[Block]) -> tuple[str, str | None, list[HistEntry]]:
    title, code, hist = "", None, []
    for b in blocks:
        t = b.text
        if m := RE_CLASS.search(t):
            code = re.sub(r"\s+", "", m[1])
            continue
        if m := RE_HIST.match(t):
            hist.append(HistEntry(re.sub(r"\s+", "", m[1]), parse_dot_date(m[2]), m[3]))
            continue
        if not title and not RE_LEADER.search(t) and not re.fullmatch(r"[\d\s.-]+", t) and "목" not in t[:2]:
            title = _despace_title(re.sub(r"\(\s*원규분류.*$", "", t).strip())
    return title, code, hist


def _is_toc_entry(blocks: list[Block], i: int) -> bool:
    """제목만 있고 본문이 없으며 바로 다음 줄도 조문 머리인 줄은 목차 항목이다."""
    m = RE_ARTICLE.match(blocks[i].text)
    if not m or (m[4] or "").strip():
        return False
    nxt = blocks[i + 1].text if i + 1 < len(blocks) else ""
    return bool(RE_ARTICLE.match(nxt) or RE_CHAPTER.match(nxt))


def _body_start(blocks: list[Block]) -> int:
    first = next((i for i, b in enumerate(blocks)
                  if (m := RE_ARTICLE.match(b.text)) and m[3] and not RE_LEADER.search(b.text)
                  and not _is_toc_entry(blocks, i)), None)
    if first is None:
        return len(blocks)
    for i in range(first - 1, max(first - 4, -1), -1):
        if (m := RE_CHAPTER.match(blocks[i].text)) and int(m[1]) == 1:
            return i
    return first


def _pre_split(blocks: list[Block]) -> list[Block]:
    """한 문단에 이어 붙은 항(…한다.②…)을 줄로 나눈다 (HWP)."""
    out = []
    for b in blocks:
        parts = INLINE_PARA.split(b.text)
        out.extend(Block(p.strip(), b.page, b.bbox) for p in parts if p.strip())
    return out


def parse_blocks(blocks: list[Block]) -> ParsedDoc:
    blocks = [b for b in blocks if b.text]
    start = _body_start(blocks)
    title, code, hist = _header(blocks[:start])
    toc = []
    for b in blocks[:start]:
        if m := RE_ARTICLE.match(b.text):
            k = _article_key(m[1], m[2])
            if k not in toc:
                toc.append(k)
    body = [b for b in _pre_split(blocks[start:]) if not RE_LEADER.search(b.text) or RE_ARTICLE.match(b.text)]
    B = _Builder(Joiner([b.text for b in body]))
    annexes = 0
    in_annex = False

    for b in body:
        t = b.text
        if m := RE_ANNEX.match(t):
            if t.lstrip()[:1] in "<[〈" or m[4] == "" or m[4][0] in "<(〈[":
                kind = "annex" if "표" in m[1] else "form"
                key = f"{kind}{int(m[2])}" + (f"-{int(m[3])}" if m[3] else "")
                if any(p.path == key for p in B.provs):
                    key = f"{key}~{sum(1 for p in B.provs if p.path.startswith(key)) + 1}"
                label = ("별표" if kind == "annex" else "별지") + f" 제{int(m[2])}호" + (f"의{int(m[3])}" if m[3] else "")
                B.add(Prov(key, "annex", label, heading=clean(m[4]) or None), b)
                in_annex, annexes = True, annexes + 1
                continue
        if in_annex:
            B.append_text(t)
            continue
        if (m := RE_SUPPL.match(t)) and (m[1] is not None or not m[2] or RE_LAWNO.match(m[2])):
            d = parse_dot_date(m[1] or "")
            base = f"supp@{d.isoformat()}" if d else f"supp#{len(B.supp_dates) + 1}"
            n = B.supp_dates.get(base, 0) + 1
            B.supp_dates[base] = n
            path = base if n == 1 else f"{base}~{n}"
            B.supp = B.add(Prov(path, "supplement", "부칙", meta={"date": d.isoformat() if d else None}), b)
            B.article = B.para = B.item = None
            if m[2]:
                B.append_text(m[2])
            continue
        if B.supp is None and (m := RE_CHAPTER.match(t)) and int(m[1]) == B.last_chapter + 1:
            B.last_chapter = int(m[1])
            B.chapter, B.section = f"c{int(m[1])}", None
            B.add(Prov(B.chapter, "chapter", f"제{int(m[1])}장", heading=_despace_title(clean(m[2])) or None), b)
            B.cur = None
            continue
        if B.supp is None and B.chapter and (m := RE_SECTION.match(t)):
            B.section = f"{B.chapter}-s{int(m[1])}"
            B.add(Prov(B.section, "section", f"제{int(m[1])}절", heading=clean(m[2]) or None, parent=B.chapter), b)
            B.cur = None
            continue
        if (m := RE_ARTICLE.match(t)) and (m[3] or re.match(r"삭\s*제", m[4] or "")) \
                and not PARTICLE.match((m[4] or "").strip()):
            num = _num(m[1], m[2])
            in_supp = B.supp is not None
            if in_supp or num > B.last_art:
                key = _article_key(m[1], m[2])
                if in_supp:
                    key, parent, unit = f"{B.supp.path}/{key}", B.supp.path, "supp_article"
                else:
                    parent, unit = B.section or B.chapter, "article"
                    B.last_art = num
                label = f"제{int(m[1])}조" + (f"의{int(m[2])}" if m[2] else "")
                B.article = B.add(Prov(key, unit, label, heading=clean(m[3]) if m[3] else None, parent=parent), b)
                B.para = B.item = None
                rest = (m[4] or "").strip()
                if rest and rest[0] in CIRCLED:
                    _para(B, rest, b)
                elif rest:
                    B.append_text(rest)
                continue
        if B.article is not None and re.fullmatch(r"\[[^\[\]]*\]", t):  # 조문 끝의 [본조신설 …]은 조문에 붙는다
            B.article.annotations.append(t)
            continue
        if B.article is not None and t[0] in CIRCLED:
            _para(B, t, b)
            continue
        if B.article is not None and (m := RE_ITEM.match(t)):
            parent = B.para or B.article
            key = f"{parent.path}.i{int(m[1])}" + (f"-{int(m[2])}" if m[2] else "")
            if any(p.path == key for p in B.provs):
                B.append_text(t)
                continue
            B.item = B.add(Prov(key, "item", f"{int(m[1])}." if not m[2] else f"{int(m[1])}의{int(m[2])}.",
                                parent=parent.path), b)
            B.append_text(m[3])
            continue
        if B.item is not None and (m := RE_SUB.match(t)):
            key = f"{B.item.path}.s{m[1]}"
            B.add(Prov(key, "subitem", f"{m[1]}.", parent=B.item.path), b)
            B.append_text(m[2])
            continue
        B.append_text(t)

    for p in B.provs:
        _finish(p)
    st = {u: sum(1 for p in B.provs if p.unit == k) for u, k in
          [("articles", "article"), ("paragraphs", "paragraph"), ("items", "item"), ("supplements", "supplement"),
           ("annexes", "annex")]}
    st["unparsed_lines"] = B.unparsed
    return ParsedDoc(title, code, [h for h in hist if h.date], B.provs,
                     {"stats": st, **({"toc": toc} if len(toc) >= 3 else {})})


def _para(B: _Builder, t: str, b: Block) -> None:
    n = CIRCLED.index(t[0]) + 1
    key = f"{B.article.path}.p{n}"
    if any(p.path == key for p in B.provs):
        B.append_text(t)
        return
    B.para = B.add(Prov(key, "paragraph", t[0], parent=B.article.path), b)
    B.item = None
    B.append_text(t[1:].strip())
