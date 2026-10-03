"""비교값 정규화·검증 (spec §4: 다수 값 = 정규화 값의 최빈값, 인용은 원문 그대로)."""
import re
from collections import Counter

_WS = re.compile(r"\s+")
_DURATION = re.compile(r"(\d+)\s*(주일|개월|일|주|월|년)")
_WON_PART = re.compile(r"(\d+(?:\.\d+)?)(억|천만|백만|십만|만|천|백)?")
_WON_UNITS = {"억": 10**8, "천만": 10**7, "백만": 10**6, "십만": 10**5, "만": 10**4, "천": 10**3, "백": 100, None: 1}
_WON = re.compile(r"\d[\d,]*(?:\.\d+)?\s*(?:억|천만|백만|십만|만|천|백)?(?:\s*\d[\d,]*\s*(?:천만|백만|십만|만|천|백))*\s*원")
_YES = {"있음", "있다", "예", "네", "필요", "필요함", "해당", "가능", "허용", "o", "y", "yes"}
_NO = {"없음", "없다", "아니오", "아니요", "불필요", "해당없음", "불가", "불가능", "허용안함", "x", "n", "no"}


def _text(value: str) -> str | None:
    v = _WS.sub("", value or "").replace("부터", "~")
    return v or None


_DURATION_VALUE = re.compile(r"(?:.*?(?:후|부터))?(\d+)(주일|개월|일|주|월|년)(?:이내|이내에|내|안|간|동안|이상|까지)?\.?")


def duration(value: str) -> str | None:
    """'7일', '7일 이내', '종료 후 2주' → 7일·14일. 날짜('다음 달 10일까지')는 기간이 아니다."""
    m = _DURATION_VALUE.fullmatch(_WS.sub("", value or ""))
    if not m:
        return None
    n, unit = int(m[1]), m[2]
    if unit in ("주", "주일"):
        return f"{n * 7}일"
    return f"{n}개월" if unit in ("개월", "월") else f"{n}{unit}"


def won(value: str) -> str | None:
    """'2천만원', '2,000만원', '1억 5천만원', '20,000천원', '50,000원' → 원 단위 정수 글."""
    s = _WS.sub("", value or "").replace(",", "")
    m = re.search(r"\d", s)
    if not m:
        return None
    s = s[m.start():]
    total, pos, seen = 0.0, 0, False
    while (p := _WON_PART.match(s, pos)) and p.end() > pos:
        total += float(p[1]) * _WON_UNITS[p[2]]
        pos, seen = p.end(), True
        if p[2] is None:
            break
    return str(int(round(total))) if seen and total > 0 else None


def boolean(value: str) -> str | None:
    v = _WS.sub("", value or "").lower().rstrip(".")
    return "있음" if v in _YES else "없음" if v in _NO else None


RULES = {"duration": duration, "won": won, "boolean": boolean, "text": _text}


def normalize(value: str, rule: str) -> str | None:
    """규칙대로 바꾸고, 바꿀 수 없으면 공백을 지운 글(같은 글끼리는 같게 센다)."""
    if not (value or "").strip():
        return None
    return RULES[rule](value) or _text(value)


def _amounts(quote: str, rule: str) -> set[str]:
    if rule == "duration":
        return {duration(m[0]) for m in _DURATION.finditer(quote)} - {None}
    if rule == "won":
        return {w for m in _WON.finditer(quote) if (w := won(m[0]))}
    return set()


def value_supported(value: str, rule: str, quote: str) -> bool:
    """숫자 값(기간·금액)은 같은 값이 인용 안에 있어야 한다. 모델이 숫자를 지어내는 것을 막는다."""
    if rule not in ("duration", "won"):
        return True
    v = RULES[rule](value)
    return v is None or v in _amounts(quote, rule)   # 숫자가 아닌 값(실비)은 인용 일치로만 본다


def majority(values: list[str | None]) -> tuple[str, int] | None:
    """정규화 값의 최빈값. 2개 기관 이상이고 1위가 하나일 때만."""
    c = Counter(v for v in values if v)
    top = c.most_common(2)
    if not top or top[0][1] < 2 or (len(top) > 1 and top[1][1] == top[0][1]):
        return None
    return top[0]


def _branch(n: str | None) -> str:
    return f"의{int(n)}" if n else ""


def path_label(path: str) -> str:
    """조항 경로 → 화면 라벨: a3-2.p2.i3-2.s가 → 제3조의2 제2항 제3호의2 가목."""
    p = path.split("#")[0]
    if m := re.fullmatch(r"annex(\d+)(?:-(\d+))?.*", p):
        return f"별표 {int(m[1])}{_branch(m[2])}"
    if m := re.fullmatch(r"form(\d+)(?:-(\d+))?.*", p):
        return f"별지 제{int(m[1])}호{_branch(m[2])}서식"
    prefix = ""
    if p.startswith("supp"):
        prefix, _, p = p.partition("/")
        prefix = "부칙"
        if not p:
            return prefix
    out = []
    for seg in p.split("."):
        if m := re.fullmatch(r"a(\d+)(?:-(\d+))?(?:~\d+)?", seg):
            out.append(f"제{int(m[1])}조{_branch(m[2])}")
        elif m := re.fullmatch(r"p(\d+)(?:~\d+)?", seg):
            out.append(f"제{int(m[1])}항")
        elif m := re.fullmatch(r"i(\d+)(?:-(\d+))?(?:~\d+)?", seg):
            out.append(f"제{int(m[1])}호{_branch(m[2])}")
        elif m := re.fullmatch(r"s([가-힣])(?:~\d+)?", seg):
            out.append(f"{m[1]}목")
    return " ".join(([prefix] if prefix else []) + out)


def squash(s: str) -> str:
    return _WS.sub("", s or "")


def quote_span(quote: str, text: str) -> tuple[int, int] | None:
    """공백을 무시하고 인용을 원문에서 찾는다. (시작, 끝) — 원문 글자 위치. 없으면 None."""
    nq = squash(quote)
    pos = [i for i, ch in enumerate(text or "") if not ch.isspace()]
    nt = "".join(text[i] for i in pos)
    if not nq or (at := nt.find(nq)) < 0:
        return None
    return pos[at], pos[at + len(nq) - 1] + 1


def value_span(value: str, rule: str, text: str, within: tuple[int, int] | None = None) -> tuple[int, int] | None:
    """강조할 값 글자 위치: 인용 안에서 값과 같은 기간·금액 표현, 없으면 값 글자 그대로."""
    s, e = within or (0, len(text))
    seg = text[s:e]
    want = RULES[rule](value) if rule in ("duration", "won") else None
    if want:
        pat = _DURATION if rule == "duration" else _WON
        for m in pat.finditer(seg):
            if RULES[rule](m[0]) == want:
                return s + m.start(), s + m.end()
    got = quote_span(value, seg) if value else None
    return (s + got[0], s + got[1]) if got else None
