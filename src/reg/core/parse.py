"""내부규정 공통 구조 파서: Block 줄/문단 → ParsedDoc.

머리부(제목·원규분류·개정 이력·목차) → 본문(장·절·조·항·호·목) → 부칙 → 별표·별지 순서로 읽는다.
본문 시작 = 제목 괄호가 있는 첫 조문(목차 줄은 괄호가 없다), 그 앞의 가장 가까운 '제1장'이 있으면 거기부터.
"""
import re

from reg.core.model import Block, HistEntry, ParsedDoc, Prov
from reg.core.text import Joiner, clean, despace_line, normalize_glyphs, parse_dot_date, split_notes

PARSER_VERSION = "2026.10.7"  # 【】·■ [ ]·글 중간 별표 머리, 겹쳐 찍힌 글자 (재파싱 필요)

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
RE_CHAPTER = re.compile(r"^제\s*(\d+)\s*장\s*(.{0,30})$")
RE_SECTION = re.compile(r"^제\s*(\d+)\s*절\s*(.{0,30})$")
RE_SUPPL = re.compile(r"^부\s*칙\s*(?:[<〈(](.*?)[>〉)])?\s*(.*)$")
RE_ARTICLE = re.compile(r"^제\s*(\d+)\s*조(?:\s*의\s*(\d+))?\s*"
                        r"(?:\(\s*((?:[^()]|\([^()]{0,20}\)){1,40}?)\s*\))?\s*(.*)$")
RE_ITEM = re.compile(r"^(\d{1,3})(?:\s*의\s*(\d+))?\.(?!\d)\s*(.*)$")  # 날짜(2024. 3. 1.)·소수(3.5)는 호가 아니다
RE_SUB = re.compile(r"^([가-하])\.\s*(.*)$")
RE_HIST = re.compile(r"^(제\s*정|전\s*부\s*개\s*정|일\s*부\s*개\s*정|개\s*정|폐\s*지)\s*"
                     r"(\d{4}\s*\.\s*\d{1,2}\s*\.\s*\d{1,2})\s*\.?\s*(?:(?:규|훈령|예규|규정)?\s*제?\s*(\d+)\s*호)?")
RE_CLASS = re.compile(r"원규\s*분류\s*(?:기\s*호)?\s*[:：]\s*([^)）]+?)\s*[)）]?\s*$")
RE_LEADER = re.compile(r"[·.…]{2,}|·\s*·|^[·\s]+$|\s·$")
PARTICLE = re.compile(r"^(?:에서|에|의|을|를|과|와|및|으로|로)(?:\s|$)")
RE_LAWNO = re.compile(r"^[<(〈]?\s*제\s*\d+\s*호")
INLINE_PARA = re.compile(r"(?<=[.。>\]」)])\s*(?=[①-⑳])")
# 별표·별지 머리: [별지 제1호] · <별표 5의2> · 【별지 제1호 서식】 · 【별표 제1호_제목】 · [별표1: 제목] · ■ [별지 제4-1호]
# '제4-1호'의 '-1'은 가지번호(의1)로 보지 않는다: 참조 추출(refs.RE_ANNEX)이 '별지 제4-1호'를 form4로 읽으므로 경로도 form4(~n)다.
RE_ANNEX = re.compile(r"^(?P<dec>■\s*)?(?P<open>[<\[〈【])?\s*(?P<kind>별\s*표|별\s*지)\s*(?:제\s*)?(?P<no>\d+)\s*(?:호)?"
                      r"(?:\s*의\s*(?P<sub>\d+)\s*(?:호)?|\s*-\s*(?P<dash>\d+)\s*(?:호)?)?\s*(?:서식)?"
                      r"(?:(?:\s*[_:]\s*|(?<=서식))(?P<title>[^<>\[\]〈〉【】]*?)(?=\s*[>\]〉】]))?\s*(?P<close>[>\]〉】])?\s*(?P<rest>.*)$")
_CLOSER = {"<": ">", "[": "]", "〈": "〉", "【": "】"}
_NOTE_IN_BRACKET = re.compile(r"^(?:개정|신설|삭제|이동|전문개정|일부개정)")
# 머리 뒤가 조사·서술어면 본문 인용이다: '[별표 1]의 기준', '【별지 제1호 서식】에 의한', '[별지 제2호 서식] 승인서로 통보하여야 한다.'
# '이·가'는 넣지 않는다('<별지 제3호 서식> 이 력 서', '[별표 제4호] 가.감산평정기준').
_CITE_PARTICLE = re.compile(r"^(?:에서|에게|에는|에도|에|의|을|를|과|와|및|으로|로|은|는|도|만)(?=[\s,.)」』’”〔\[(<]|$)")
_CITE_GLUED = re.compile(r"^(?:을|를|에\s*(?:의|따|준|대하|관하))")  # 괄호에 바로 붙은 조사 ('】을 작성', '】에의하여')
_CITE_OBJECT = re.compile(r"^\S*[가-힣](?:을|를)(?=[\s,]|$)")  # 첫 어절이 목적어 ('[별표 2] 신청서를 제출')
_CITE_PREDICATE = re.compile(r"(?:한다|하여야|하여|된다|있다|없다|같다|따른다|본다|않는다|하며|하고|한\s*후)(?=[\s.,]|$)")
_CITE_OTHER_ANNEX = re.compile(r"[<\[〈【]\s*별\s*[표지]\s*(?:제\s*)?\d")
_PAREN_NOTE = re.compile(r"[(（]\s*(?:신설|개정|삭제|전문개정|일부개정|제정)[^()（）]*[)）]")
# 글 중간 머리: 앞 글이 문장·서식 끝이거나('…시행한다. 【별지 제1호 서식】', '(인) 【별지 …】', '귀중 ■ [별지 …]')
# 바로 앞 조각도 별표 머리일 때('[별표1] 삭제 <…> [별표2] 삭제 <…>')만 나눈다
_INLINE_ANNEX = re.compile(r"(?:■\s*)?[【\[<〈]\s*별\s*[표지]")
_INLINE_BOUNDARY = re.compile(r"(?:다\s*\.|\(\s*(?:인|서명|서명\s*또는\s*인)\s*\)|귀\s*하|귀\s*중)\s*$")


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


def _title_like(rest: str, glued: bool) -> bool:
    """머리 뒤 글이 제목·주석이면 True, 조사·서술어로 이어지는 본문 인용이면 False."""
    if not rest:
        return True
    if rest[0] in ",.)」』’”:;·" or _CITE_PARTICLE.match(rest) or (glued and _CITE_GLUED.match(rest)):
        return False
    return not (_CITE_OBJECT.match(rest) or _CITE_PREDICATE.search(rest[:40]) or _CITE_OTHER_ANNEX.search(rest[:60]))


def _annex_parts(t: str) -> tuple[str, int, int | None, int | None, str, str] | None:
    """(kind, 번호, 가지번호(의N), '-N', 괄호 안 제목, 나머지)."""
    m = RE_ANNEX.match(t)
    if not m:
        return None
    opened, closed, rest = m["open"], m["close"], m["rest"]
    if not (opened or rest == "" or rest[0] in "<(〈["):
        return None
    if opened and not closed and _NOTE_IN_BRACKET.match(rest) and _CLOSER[opened] in rest:
        return None  # '<별표2 개정 2008.3.18>'은 조문 끝 개정 주석이다
    if not _title_like(rest, glued=bool(closed) and m.end("close") == m.start("rest")):
        return None
    return ("annex" if "표" in m["kind"] else "form", int(m["no"]), int(m["sub"]) if m["sub"] else None,
            int(m["dash"]) if m["dash"] else None, clean(m["title"] or ""), rest)


def annex_heading(t: str) -> tuple[str, int, int | None, str] | None:
    """별표·별지 머리 줄이면 (kind, 번호, 가지번호, 나머지). 본문 속 '별지 제1호서식에 따라'는 머리가 아니다.

    괄호([ < 〈 【)로 열거나 뒤가 비었거나 '<(〈['로 이어질 때만 머리로 보고, 뒤 글이 조사·서술어면 인용으로 본다.
    【별표 제1호_제목】의 괄호 안 제목은 나머지 앞에 붙인다."""
    a = _annex_parts(t)
    return a and (a[0], a[1], a[2], " ".join(x for x in a[4:] if x))


def split_inline_annex(t: str) -> list[str]:
    """줄 중간의 별표·별지 머리 앞에서 줄을 나눈다 ('…에 따라 [별지 제2호 서식] 승인서로' 같은 인용은 그대로).

    후보(닫는 괄호가 있는 머리) 사이 조각마다, 그 조각이 머리이고 ① 앞 글이 문장·서식 끝이며 뒤에 제목이 있거나
    ② 바로 앞 조각도 머리일 때만 나눈다. 받지 않은 후보는 앞 조각에 다시 붙인다."""
    cuts = [m.start() for m in _INLINE_ANNEX.finditer(t)
            if m.start() > 0 and (r := RE_ANNEX.match(t[m.start():])) and r["close"]]
    if not cuts:
        return [t]
    out = [t[:cuts[0]]]
    for i, c in enumerate(cuts):
        seg = t[c:cuts[i + 1] if i + 1 < len(cuts) else len(t)]
        h = annex_heading(seg)
        prev = out[-1].rstrip()
        if h and ((h[3] and _INLINE_BOUNDARY.search(prev)) or annex_heading(prev)):
            out[-1] = prev
            out.append(seg)
        else:
            out[-1] += seg
    return [x.strip() for x in out if x.strip()]


def _finish(p: Prov) -> None:
    p.text = normalize_glyphs(p.text)
    if p.heading:
        p.heading = normalize_glyphs(p.heading)
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
        parts = [q for p in INLINE_PARA.split(b.text) for q in split_inline_annex(p)]
        out.extend(Block(p.strip(), b.page, b.bbox) for p in parts if p.strip())
    return out


def parse_blocks(blocks: list[Block]) -> ParsedDoc:
    blocks = [Block(despace_line(b.text), b.page, b.bbox) for b in blocks if b.text]
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
        if ah := _annex_parts(t):
            kind, no, sub, dash, atitle, rest = ah
            key = f"{kind}{no}" + (f"-{sub}" if sub else "")
            if any(p.path == key for p in B.provs):
                key = f"{key}~{sum(1 for p in B.provs if p.path.startswith(key)) + 1}"
            label = ("별표" if kind == "annex" else "별지") + (f" 제{no}-{dash}호" if dash else f" 제{no}호") \
                + (f"의{sub}" if sub else "")
            rest, notes = split_notes(rest)  # '[별지 제1호]<개정 2019.7.5.>': 개정 표시는 제목이 아니라 주석
            notes += _PAREN_NOTE.findall(rest)  # 【별지 제2호 서식】(개정 2018. 5.29)
            rest = clean(_PAREN_NOTE.sub(" ", rest))
            heading, rest = (atitle, rest) if atitle else (rest, "")  # 【별표 제1호_제목】 뒤 글은 본문
            B.add(Prov(key, "annex", label, heading=heading or None, annotations=notes), b)
            if rest:
                B.append_text(rest)
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
