"""조문 번호 인용 파서 (M7 spec §2.2-1): "천문연 여비규정 27조 1항" → 기관·규정명·조·항·호·목.

번호(조 또는 별표·별지)가 없으면 인용이 아니다(None). 기관은 약칭표(코드 → [정식명, 약칭…])로 찾고,
규정명은 번호 앞에서 기관 언급을 뺀 나머지다."""
import re
from dataclasses import asdict, dataclass

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
RE_ANNEX = re.compile(r"(별표|별지)\s*(?:제\s*)?(\d+)\s*(?:호)?(?:\s*의\s*(\d+))?(?:\s*서식)?")
RE_ART = re.compile(r"제?\s*(\d+)\s*조(?:\s*의\s*(\d+))?")
RE_PARA = re.compile(r"^\s*(?:제?\s*(\d+)\s*항|([①-⑳]))")
RE_ITEM = re.compile(r"^\s*제?\s*(\d+)\s*호(?:\s*의\s*(\d+))?")
RE_SUB = re.compile(r"^\s*([가-하])\s*목")
QUOTES = "「」『』\"'“”‘’<>《》"


@dataclass
class Citation:
    institution: str | None = None
    title: str | None = None
    article: int | None = None
    branch: int | None = None
    paragraph: int | None = None
    item: int | None = None
    item_branch: int | None = None
    subitem: str | None = None
    annex: int | None = None
    form: bool = False

    def unit(self) -> str:
        if self.annex is not None:
            return "form" if self.form else "annex"
        return "subitem" if self.subitem else "item" if self.item is not None else \
            "paragraph" if self.paragraph is not None else "article"

    def as_dict(self) -> dict:
        return asdict(self)


def _institution(head: str, aliases: dict[str, list[str]] | None) -> tuple[str | None, str]:
    """번호 앞부분에서 기관 언급을 찾아 빼낸다. 둘 이상의 기관이 보이면 기관을 정하지 않는다."""
    if not aliases:
        return None, head
    found, rest = set(), head
    pairs = sorted(((a, code) for code, al in aliases.items() for a in {*al, code} if a), key=lambda x: -len(x[0]))
    for alias, code in pairs:
        tail = r"(?![A-Za-z0-9])" if alias.isascii() else ""
        pat = re.compile(r"(?<![A-Za-z0-9가-힣])" + re.escape(alias) + tail, re.IGNORECASE)
        if pat.search(rest):
            found.add(code)
            rest = pat.sub(" ", rest)
    return (found.pop() if len(found) == 1 else None), rest


def mentioned_institution(text: str, aliases: dict[str, list[str]] | None) -> str | None:
    """번호 인용이 아닌 질의의 기관 언급("천문연 출장 증빙") → 코드. 없거나 둘 이상이면 None (QA resolve_mention과 같은 규칙)."""
    return _institution(text or "", aliases)[0]


def _title(rest: str) -> str | None:
    t = rest.translate({ord(c): " " for c in QUOTES})
    t = re.sub(r"^\s*(?:의|에서|에|중)\s+", "", " " + t.strip() + " ").strip()
    t = re.sub(r"\s+(?:의|에서|에|중)$", "", t)
    t = re.sub(r"\s+", " ", t).strip(" ,.:·")
    return t or None


def parse_citation(q: str, aliases: dict[str, list[str]] | None = None) -> Citation | None:
    s = (q or "").strip()
    if not s:
        return None
    c = Citation()
    m = RE_ANNEX.search(s)
    a = RE_ART.search(s)
    if m and (a is None or m.start() < a.start()):
        c.annex, c.form = int(m[2]), m[1] == "별지"
        start = m.start()
    elif a:
        c.article, c.branch = int(a[1]), int(a[2]) if a[2] else None
        start = a.start()
        rest = s[a.end():]
        if p := RE_PARA.match(rest):
            c.paragraph = int(p[1]) if p[1] else CIRCLED.index(p[2]) + 1
            rest = rest[p.end():]
        if i := RE_ITEM.match(rest):
            c.item, c.item_branch = int(i[1]), int(i[2]) if i[2] else None
            rest = rest[i.end():]
            if sb := RE_SUB.match(rest):
                c.subitem = sb[1]
    else:
        return None
    c.institution, rest_head = _institution(s[:start], aliases)
    c.title = _title(rest_head)
    return c
