"""조문 본문의 참조 추출(규칙 기반)과 대상 해석 (spec 6.4, M6-6 개정).

M6-6에서 바뀐 것 (실측: 현행 표본 정밀도 64.6% → 91.9%)
- 괄호 없는 규범 이름("연구관리규정 제2조", "근로기준법 제74조")을 이름 참조(kind="named")로 뽑는다.
  같은 기관 규정 제목·법령 제목으로 해석하고, 못 찾으면 자기 조문이 아니라 미해석 외부 참조로 남긴다.
- 문서 안 약칭 정의("「공직자의 이해충돌 방지법」(이하 “법”이라 한다)")로 "법 제24조"를 그 법으로 잇는다.
- 이름 뒤에 이어지는 조·별표 나열, "동 요령", 부칙의 "X 일부를 다음과 같이 개정한다" 범위는 앞 이름을 잇는다.
- "제72조제3항 및 제4항"의 제4항, "같은 조 제4항"은 앞 조의 항이다.
- 별표·서식 안의 계약서 조항("제1조(총칙)")은 본문 조문 참조가 아니다("(제7조 관련)"은 참조).
- 따옴표 안의 "따로 정한다"는 위임이 아니다. "세부사항은 인사관리요령에서 정한다"는 그 규정으로의 위임(DELEGATION)이다.
- 목적 조문의 "X 제N조에 의거 … 필요한 사항을 정함", "X에서 위임한"은 상위 규범을 시행하는 관계(IMPLEMENTS)다.
"""
import re
from dataclasses import dataclass, field
from datetime import date

from reg.core.ingest.loader import norm_title
from reg.core.model import Prov

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
RE_NAME = re.compile(r"「\s*([^」]{2,80}?)\s*」")
RE_ART = re.compile(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+)(?!\d))?(?:\s*제\s*(\d+)\s*항)?(?:\s*제\s*(\d+)\s*호)?"
                    r"(?:\s*([가-하])\s*목)?")
AFTER_JO = r"(?=\s|에|의|를|은|는|와|과|부터|까지|[,.)]|$)"  # '이 조치'처럼 다른 낱말이 이어지면 참조가 아니다
RE_PARA_ONLY = re.compile(r"(?<![조\d])\s?제\s*(\d+)\s*항|전\s*항|같은\s*조" + AFTER_JO + r"|이\s*조" + AFTER_JO)
RE_JOIN = re.compile(r"\s*(?:및|,|·|ㆍ|와|과|또는|이나)\s*")
RE_SAME = re.compile(r"(?:같은\s*법|동\s*법)(\s*시행령|\s*시행규칙)?\s*$")
RE_ANNEX = re.compile(r"(별\s*표|별\s*지)\s*(?:제\s*)?(\d+)\s*(?:호)?(?:\s*의\s*(\d+))?")
RE_DELEG = re.compile(r"(?:따로|별도로)\s*정한다|(?:으)?로\s*정하는\s*바에\s*따른다")
LAW_TAIL = re.compile(r"(법|법률|령|규칙|규정|예규|훈령|고시|지침|기준)$")

REG_WORDS = "규정|요령|지침|기준|세칙|규칙|내규|정관|편람|강령"
LAW_WORDS = "법률|법|시행령|시행규칙"
REG_SUFFIX = f"(?:{REG_WORDS})"
LAW_SUFFIX = f"(?:{LAW_WORDS})"
# 조문 번호 바로 앞(공백 0~1개)의 이름 한 덩어리: '연구관리규정', '근로기준법', '근로기준법 시행령'
RE_NAME_TAIL = re.compile(rf"([가-힣A-Za-z0-9·ㆍ]{{1,40}}?(?:{REG_WORDS}|{LAW_WORDS}))(\s?(?:시행령|시행규칙))?\s?$")
# '… 등에 관한 법률 제5조'처럼 띄어 쓴 긴 법률 이름 (쉼표·마침표·괄호 뒤부터)
RE_LONG_LAW = re.compile(r"(?:^|[,.;:)」]\s?|\s(?:및|또는)\s)((?:[가-힣A-Za-z0-9·ㆍ]+\s){1,9}?[가-힣A-Za-z0-9·ㆍ]*관한\s?법률"
                         r"(?:\s?시행령|\s?시행규칙)?)\s?$")
RE_QUAL = re.compile(r"(?:^|\s)((?:이|본|동|같은|당해)\s?" + REG_SUFFIX + r")\s?$")
BARE_LAW = {"법", "영", "법률", "시행령", "시행규칙"}
STANDALONE = {"정관"}  # 접미어만으로 된 규범 이름
SELF_WORDS = re.compile(r"^(?:이|본|당해)\s?" + REG_SUFFIX + "$|^" + REG_SUFFIX + "$")
SAME_WORDS = re.compile(r"^(?:동|같은)\s?" + REG_SUFFIX + "$")
GENERIC = re.compile(r"^(?:관련|관계|해당|각|위|다른|내부|제|상기|소관|별도|운영|세부|시행|기관)\s?" + REG_SUFFIX + "$"
                     r"|^(?:관련|관계|해당|각|다른|이|본|당해)\s?" + LAW_SUFFIX + "$")
RE_DEF = re.compile(r"(?:「\s*([^」]{2,80}?)\s*」|([가-힣A-Za-z0-9·ㆍ]{2,40}(?:법|법률|령|" + REG_WORDS + r")))"
                    r"\s?\(\s?이하\s?[“\"‘']\s?([^”\"’']{1,12}?)\s?[”\"’']\s?(?:이)?라\s?(?:한다|함)")
RE_SAME_DEF = re.compile(r"같은\s?법\s?(시행령|시행규칙)\s?\(\s?이하\s?[“\"‘']\s?([^”\"’']{1,6}?)\s?[”\"’']")
RE_ANY_DEF = re.compile(r"([가-힣A-Za-z0-9·ㆍ]{2,40})\s?\(\s?이하\s?[“\"‘']\s?([^”\"’']{1,12}?)\s?[”\"’']"
                        r"\s?(?:이)?라\s?(?:한다|함)")
RE_AMEND = re.compile(r"((?:[가-힣A-Za-z0-9·ㆍ]{2,20}\s)?[가-힣A-Za-z0-9·ㆍ]{0,40}" + REG_SUFFIX
                      + r")\s?(?:일부|전부)를\s?다음과\s?같이\s?개정한다")
RE_CONT = re.compile(r"[\s,·ㆍ]*(?:및|와|과|또는|이나|부터|까지)?[\s,·ㆍ]*")
RE_LIST_GAP = re.compile(r"[\s,·ㆍ]*(?:및|와|과|또는|이나|중)?[\s,·ㆍ]*")
RE_OWN_CLAUSE = re.compile(r"제\s?\d+\s?조\s?\([^)]{1,20}\)")
RE_RELATED = re.compile(r"\(\s?제\s?\d+\s?조[^()]{0,20}관련\s?\)")
RE_DELEG_NAMED = re.compile(r"([가-힣A-Za-z0-9·ㆍ]{2,40}" + REG_SUFFIX + r")\s?(?:에서|으로|로)\s?(?:따로\s?|별도로\s?)?"
                            r"정(?:한다|할\s?수\s?있다|하는\s?바에\s?따른다)")
RE_PURPOSE_BASIS = re.compile(r"^\s?(?:\([^()]{1,20}\)\s?)?(?:에\s?의거|에\s?의하여|에\s?따라|에\s?근거하여"
                              r"|의\s?규정에\s?(?:의하여|따라|의거)|에서\s?위임)")
RE_NAME_WORK = re.compile(rf"(?<![가-힣A-Za-z0-9·ㆍ「“])([가-힣A-Za-z0-9·ㆍ]{{1,40}}(?:{REG_WORDS}|{LAW_WORDS}))"
                          r"(?=\s?(?:에서|에|을|를|의|으로부터)\s?(?:따라|따른|의하여|의한|의거|정하는|정한|준용|근거|위임))")
RE_WIIM = re.compile(r"^\s?(?:에서|으로부터)\s?위임(?:한|된|받은)")
INST_WORDS = ("연구원", "연구회", "과기연", "천문연", "본원", "당원")


@dataclass
class RefCandidate:
    path: str
    start: int
    end: int
    evidence: str
    rel_type: str
    kind: str  # internal | external | named | annex | named_annex | delegation | delegation_named
    name: str | None
    target_path: str | None
    confidence: float = 1.0
    extractor: str = "rule"


@dataclass
class RefContext:
    """문서(판본) 단위 정보: 약칭 정의. resolve_and_store가 모든 조항 본문에서 먼저 모은다."""
    abbreviations: dict[str, str] = field(default_factory=dict)


def collect_definitions(texts: list[str]) -> dict[str, str]:
    """모든 '(이하 “X”라 한다)' 정의: {"연구원": "한국전자통신연구원"} — 기관명 약칭을 찾는 데 쓴다."""
    out: dict[str, str] = {}
    for t in texts:
        for m in RE_ANY_DEF.finditer(t or ""):
            out.setdefault(m[2].strip(), m[1])
    return out


def collect_abbreviations(texts: list[str]) -> dict[str, str]:
    """'「공직자의 이해충돌 방지법」(이하 “법”이라 한다)' → {"법": "공직자의 이해충돌 방지법"}. 같은 법 시행령 약칭도."""
    out: dict[str, str] = {}
    for t in texts:
        last = None
        for m in RE_DEF.finditer(t or ""):
            full = (m[1] or m[2]).strip()
            if full in BARE_LAW:
                continue  # '같은 법 시행령(이하 “영”…)'의 '시행령'만 잡힌 경우: 아래 RE_SAME_DEF가 맡는다
            if looks_like_law(full) or re.search(REG_SUFFIX + "$", full):
                out.setdefault(m[3].strip(), full)
                last = full
        if last:
            for m in RE_SAME_DEF.finditer(t):
                out.setdefault(m[2].strip(), f"{last} {m[1]}")
    return out


def looks_like_law(name: str) -> bool:
    return bool(LAW_TAIL.search(norm_title(name)))


def _art_path(m) -> str:
    p = f"a{int(m[1])}" + (f"-{int(m[2])}" if m[2] else "")
    if m[3]:
        p += f".p{int(m[3])}"
    if m[4]:
        p += f".i{int(m[4])}"
    if m[5]:
        p += f".s{m[5]}"
    return p


def _rel(text: str, end: int, external: bool) -> str:
    after = text[end:end + 30]
    if re.match(r"\s*(?:의\s*규정)?\s*에도\s*불구하고", after):
        return "EXCEPTION"
    if "준용" in after.split("다.")[0]:
        return "MUTATIS"
    if external and re.match(r"\s*(?:\([^()]{1,20}\)\s*)?(?:의\s*규정)?\s*에\s*(?:따라|따른|의하여|의한|근거하여|근거한)",
                             after):
        return "BASIS"
    return "CITATION"


def _article_of(path: str) -> str:
    return path.split(".")[0]


def _in_quotes(text: str, pos: int) -> bool:
    before = text[:pos]
    return before.count("“") > before.count("”") or before.count('"') % 2 == 1


def _name_before(text: str, start: int, abbr: dict[str, str]) -> tuple[str, int] | None:
    """조·별표 번호 바로 앞의 이름과 그 시작 위치. '이 규정'·'동 요령'은 그 말 그대로, '관련 규정'은 None."""
    off = max(0, start - 120)
    pre = text[off:start]
    tok = re.search(r"([가-힣A-Za-z0-9·ㆍ]{1,40})\s?$", pre)
    if tok and tok[1] in abbr:
        return abbr[tok[1]], off + tok.start(1)
    if tok and tok[1] in STANDALONE:
        return tok[1], off + tok.start(1)
    if tok and tok[1] in BARE_LAW and not re.search(r"(?:같은|동)\s?$", pre[:tok.start(1)]):
        return tok[1], off + tok.start(1)  # 정의 없는 '법 제5조', '시행령 제18조': 자기 조문이 아니다
    if q := RE_QUAL.search(pre):  # '동 요령', '이 규정', '같은 지침'
        return q[1], off + q.start(1)
    if m := RE_LONG_LAW.search(pre):
        return re.sub(r"\s+", " ", m[1]).strip(), off + m.start(1)
    m = RE_NAME_TAIL.search(pre)
    if not m:
        return None
    name = (m[1] + (m[2] or "")).strip()
    s = off + m.start(1)
    two = re.search(r"(?:^|\s)((?:이|본|동|같은|당해|관련|관계|해당|각|다른|위|상기)\s)$", text[max(0, s - 5):s])
    if two:  # '관련 규정', '해당 지침' 같은 두 낱말 표현
        name = two[1].strip() + " " + name
        s -= len(two[1])
    elif GENERIC.match(name) and (w := re.search(r"([가-힣A-Za-z0-9·ㆍ]{2,20})\s$", text[max(0, s - 21):s])):
        name = w[1] + " " + name  # '방첩업무 시행지침'처럼 띄어 쓴 이름의 뒷말이 일반 낱말인 경우
        s -= len(w[0])
    if GENERIC.match(name.replace(" ", "")) or GENERIC.match(name):
        return None
    return name, s


def extract_refs(p: Prov, ctx: RefContext | None = None) -> list[RefCandidate]:
    text, out, taken = p.text or "", [], []
    abbr = ctx.abbreviations if ctx else {}
    in_annex = p.unit == "annex" or p.path.startswith(("annex", "form"))
    own_clauses = in_annex and len(RE_OWN_CLAUSE.findall(text)) >= 2  # 별표·서식 속 계약서 조항
    related = [(m.start(), m.end()) for m in RE_RELATED.finditer(text)]
    in_supp = p.unit in ("supplement", "supp_article") or p.path.startswith("supp")

    def free(s, e):
        return all(e <= a or s >= b for a, b in taken)

    def add(r: RefCandidate) -> RefCandidate:
        out.append(r)
        taken.append((r.start, r.end))
        return r

    # 1) 「이름」과 이어지는 조 나열
    names: list[tuple[int, str]] = []
    for m in RE_NAME.finditer(text):
        name = m[1].strip()
        names.append((m.start(), name))
        art = RE_ART.match(text, m.end()) or RE_ART.match(text, m.end() + 1)
        if art and art.start() - m.end() > 1:
            art = None
        end = art.end() if art else m.end()
        add(RefCandidate(p.path, m.start(), end, text[m.start():end], _rel(text, end, True), "external",
                         name, _art_path(art) if art else None))
        while art:  # 「법」 제5조 및 제6조: 이어지는 조도 같은 법
            j = RE_JOIN.match(text, end)
            art = RE_ART.match(text, j.end()) if j else None
            if art:
                add(RefCandidate(p.path, art.start(), art.end(), art[0], _rel(text, art.end(), True), "external",
                                 name, _art_path(art)))
                end = art.end()

    # 2) 부칙 '○○요령 일부를 다음과 같이 개정한다' → 그 뒤 이름 없는 조·별표는 ○○요령의 것
    amend = [(m.end(), m[1]) for m in RE_AMEND.finditer(text)] if in_supp else []

    # 3) 괄호 없는 조·별표 참조를 앞에서부터: 같은 법 · 이 규정 · 동 요령 · 이름 · 나열 이어짐 · 개정 범위 · 자기 조문
    hits = sorted([("art", m) for m in RE_ART.finditer(text)] + [("annex", m) for m in RE_ANNEX.finditer(text)],
                  key=lambda x: x[1].start())
    carry: RefCandidate | None = None  # 이름을 이어받을 직전 참조
    for typ, m in hits:
        if not free(m.start(), m.end()):
            r0 = next((r for r in out if r.start <= m.start() < r.end), None)
            carry = r0 if r0 and r0.name else carry
            continue
        if typ == "annex":
            target = ("annex" if "표" in m[1] else "form") + f"{int(m[2])}" + (f"-{int(m[3])}" if m[3] else "")
        else:
            target = _art_path(m)
        same = RE_SAME.search(text[:m.start()]) if typ == "art" else None
        prior = [(pos, n) for pos, n in names if pos < m.start()]
        if carry is not None and carry.name and carry.kind in ("named", "external"):
            prior.append((carry.start, carry.name))
        prior_names = [n for _, n in sorted(prior)]
        nb = _name_before(text, m.start(), abbr)
        cont = carry is not None and RE_LIST_GAP.fullmatch(text[carry.end:m.start()])
        inherited = "named" if carry is not None and carry.kind == "named_annex" else (carry.kind if carry else None)
        start, name, kind, conf, how = m.start(), None, "internal", 1.0, "rule"
        if same and prior_names:
            start, kind = same.start(), "external"
            name = prior_names[-1] + (" " + same[1].strip() if same[1] else "")
        elif nb and nb[0] not in STANDALONE and SELF_WORDS.match(nb[0].replace(" ", "")):
            pass  # '이 규정 제5조'
        elif nb and SAME_WORDS.match(nb[0].replace(" ", "")):
            if carry is not None and carry.name:
                start, name, kind, conf, how = nb[1], carry.name, inherited, 0.9, "rule:same"
        elif nb:
            start, name, kind, conf, how = nb[1], nb[0], "named", 0.9, "rule:name"
        elif cont and carry.name:  # 별표 뒤의 조는 그 규범의 조 (named_annex → named)
            name, kind, conf, how = carry.name, inherited, carry.confidence, "rule:list"
        elif amend and any(e <= m.start() for e, _ in amend):
            name, kind, conf, how = [n for e, n in amend if e <= m.start()][-1], "named", 0.9, "rule:amend"
        elif typ == "art" and own_clauses and not any(a <= m.start() < b for a, b in related):
            continue  # 별표·서식 속 계약서 자체 조항
        if typ == "annex":
            kind = "named_annex" if name else "annex"
        rel = "CITATION" if typ == "annex" else _rel(text, m.end(), kind != "internal")
        carry = add(RefCandidate(p.path, start, m.end(), text[start:m.end()], rel, kind, name, target, conf, how))

    # 4) 항만 쓴 참조: '제72조제3항 및 제4항'의 제4항, '같은 조 제4항'은 앞 조의 항
    art = _article_of(p.path)
    for m in RE_PARA_ONLY.finditer(text):
        s = m.start() + (1 if m[0][:1].isspace() else 0)
        if not free(s, m.end()):
            continue
        tok = m[0].strip()
        prev = next((r for r in sorted(out, key=lambda x: x.start, reverse=True) if r.end <= s and r.target_path
                     and r.kind not in ("annex", "named_annex")
                     and (RE_CONT.fullmatch(text[r.end:s]) or tok.startswith("같은"))), None)
        if prev is not None and (m[1] or tok.startswith("같은")):
            base = _article_of(prev.target_path)
            add(RefCandidate(p.path, s, m.end(), tok, _rel(text, m.end(), prev.kind != "internal"), prev.kind,
                             prev.name, f"{base}.p{int(m[1])}" if m[1] else base, prev.confidence, prev.extractor))
            continue
        if m[1]:
            target = f"{art}.p{int(m[1])}"
        elif tok.startswith("전"):
            cur = re.search(r"\.p(\d+)", p.path)
            if not cur or int(cur[1]) < 2:
                continue
            target = f"{art}.p{int(cur[1]) - 1}"
        else:
            target = art
        add(RefCandidate(p.path, s, m.end(), tok, _rel(text, m.end(), False), "internal", None, target))

    # 5) 위임: 이름이 있으면 그 규정으로(WORK), 없으면 대상 없음. 따옴표 안 인용은 위임이 아니다 (R6)
    #    이름만 쓴 참조(6)보다 먼저 한다: '인사관리요령에서 정한다'는 위임이지 단순 근거가 아니다
    for m in RE_DELEG_NAMED.finditer(text):
        name = m[1]
        two = re.search(r"(?:^|\s)(?:이|본|동|같은|관련|해당|각|다른)\s$", text[max(0, m.start() - 5):m.start()])
        if _in_quotes(text, m.start()) or two or SELF_WORDS.match(name) or GENERIC.match(name) \
                or not free(m.start(), m.end()):
            continue
        add(RefCandidate(p.path, m.start(), m.end(), m[0], "DELEGATION", "delegation_named", name, None, 0.8,
                         "rule:delegation"))
    for m in RE_DELEG.finditer(text):
        if _in_quotes(text, m.start()) or not free(m.start(), m.end()):
            continue
        out.append(RefCandidate(p.path, m.start(), m.end(), m[0], "DELEGATION", "delegation", None, None))

    # 6) 조 번호 없이 이름만 쓴 근거·준용·위임: '여비규정에 의하여', '회계규정에서 위임한' → 규범 전체(WORK)
    for m in RE_NAME_WORK.finditer(text):
        if not free(m.start(1), m.end(1)) or RE_ART.match(text, m.end(1) + 1) or _in_quotes(text, m.start(1)):
            continue
        name = m[1]
        two = re.search(r"(?:^|\s)(?:이|본|동|같은|관련|관계|해당|각|다른|위)\s$", text[max(0, m.start(1) - 5):m.start(1)])
        if two or SELF_WORDS.match(name) or GENERIC.match(name) or len(name) < 3:
            continue
        add(RefCandidate(p.path, m.start(1), m.end(1), name, _rel(text, m.end(1), True), "named", name, None, 0.7,
                         "rule:name-work"))

    # 7) 목적 조문의 근거 규범, 'X에서 위임한' → IMPLEMENTS (이 문서가 그 규범을 시행한다, R6)
    purpose = p.path == "a1" or (p.heading or "").strip() == "목적"
    for r in out:
        if r.kind in ("named", "external") and ((purpose and RE_PURPOSE_BASIS.match(text[r.end:r.end + 20]))
                                                or RE_WIIM.match(text[r.end:r.end + 12])):
            r.rel_type = "IMPLEMENTS"
    return sorted(out, key=lambda r: r.start)


def match_title(name: str, titles: dict[str, list[str]], prefixes: frozenset[str] = frozenset()) -> list[str]:
    """이름과 같은 제목. 없으면 기관명 접두어를 뗀 이름으로: '한국천문연구원 회계규정' → '회계규정' (R5).

    아무 접미부나 맞추지 않는다('공무원 여비 규정'이 기관의 '여비규정'으로 가면 안 된다)."""
    n = norm_title(name)
    if n in titles:
        return titles[n]
    for pre in sorted(prefixes, key=len, reverse=True):
        if n.startswith(pre) and len(n) > len(pre) + 1 and n[len(pre):] in titles:
            return titles[n[len(pre):]]
    return []


def institution_prefixes(conn, institution_id: int | None, definitions: dict[str, str]) -> frozenset[str]:
    """이름 앞에 붙어도 떼어 볼 기관 접두어: 정식명·코드·약칭(aliases)·문서의 기관 정의·일반 호칭 (R5)."""
    if institution_id is None:
        return frozenset()
    inst = conn.execute("SELECT code, name, aliases FROM regulation.institution WHERE id = %s",
                        (institution_id,)).fetchone()
    names = {norm_title(inst["name"]), inst["code"], *INST_WORDS, *(norm_title(a) for a in inst["aliases"] or [])}
    names |= {norm_title(k) for k, v in definitions.items() if norm_title(v) == norm_title(inst["name"])}
    return frozenset(names)


def resolve_and_store(conn, work_id: str) -> dict:
    conn.execute("DELETE FROM regulation.reference WHERE work_id = %s", (work_id,))
    work = conn.execute("SELECT * FROM regulation.work WHERE id = %s", (work_id,)).fetchone()
    titles: dict[str, list[str]] = {}
    for w in conn.execute("SELECT id, title FROM regulation.work WHERE id LIKE 'kr/law/%%' OR id LIKE 'kr/admrul/%%'"
                          " OR institution_id = %s",
                          (work["institution_id"],)).fetchall():
        titles.setdefault(norm_title(w["title"]), []).append(w["id"])
    pvs = conn.execute(
        "SELECT DISTINCT pv.* FROM regulation.provision_version pv JOIN regulation.provision p ON p.id = pv.provision_id"
        " WHERE p.work_id = %s", (work_id,)).fetchall()
    # 내부 참조는 그 조항 판본이 속한 버전들 중 가장 늦은 버전의 조문 목록으로 해석한다
    vrows = conn.execute(
        "SELECT vp.work_version_id AS v, pv.id AS pv, pv.path, v.effective_from FROM regulation.version_provision vp"
        " JOIN regulation.provision_version pv ON pv.id = vp.provision_version_id"
        " JOIN regulation.work_version v ON v.id = vp.work_version_id WHERE v.work_id = %s", (work_id,)).fetchall()
    vpaths: dict[str, set] = {}
    latest: dict[int, tuple] = {}
    for r in vrows:
        vpaths.setdefault(r["v"], set()).add(r["path"])
        key = (r["effective_from"] or date.min, r["v"])
        if r["pv"] not in latest or key > latest[r["pv"]]:
            latest[r["pv"]] = key
    texts = [pv["text"] for pv in pvs]
    ctx = RefContext(collect_abbreviations(texts))
    prefixes = institution_prefixes(conn, work["institution_id"], collect_definitions(texts))
    other_paths: dict[str, set] = {}

    def paths_of(wid: str) -> set:
        if wid not in other_paths:
            other_paths[wid] = {r["path"] for r in conn.execute(
                "SELECT pv.path FROM regulation.work_version v JOIN regulation.version_provision vp"
                " ON vp.work_version_id = v.id JOIN regulation.provision_version pv ON pv.id = vp.provision_version_id"
                " WHERE v.work_id = %s AND v.version_state = 'CURRENT'", (wid,)).fetchall()}
        return other_paths[wid]

    def has(paths: set, tpath: str | None) -> bool:
        return tpath is None or tpath in paths or tpath.split(".")[0] in paths

    st = {"refs": 0, "resolved": 0, "unresolved": 0, "seeds": 0, "named": 0}
    for pv in pvs:
        prov = Prov(pv["path"], pv["unit"], pv["number_label"], pv["heading"], pv["text"], pv["parent_path"])
        paths = vpaths.get(latest[pv["id"]][1], set()) if pv["id"] in latest else set()
        for r in extract_refs(prov, ctx):
            tw, tpath, kind, res = None, r.target_path, "NONE", "RESOLVED"
            if r.kind == "internal":
                tw, kind = work_id, "PROVISION"
                res = "RESOLVED" if has(paths, tpath) else "UNRESOLVED"
            elif r.kind == "annex":
                tw, kind = work_id, "ANNEX"
                res = "RESOLVED" if tpath in paths else "UNRESOLVED"
            elif r.kind != "delegation":  # external, named, named_annex, delegation_named
                hits = titles.get(norm_title(r.name), []) if r.kind == "external" \
                    else match_title(r.name, titles, prefixes)
                if len(hits) == 1:
                    tw = hits[0]
                    target_paths = paths if tw == work_id else paths_of(tw)
                    if r.kind == "named_annex":
                        kind = "ANNEX"
                        res = "RESOLVED" if tpath in target_paths else "UNRESOLVED"
                    else:
                        kind = "PROVISION" if tpath else "WORK"
                        res = "RESOLVED" if not tpath or has(target_paths, tpath) or tw.startswith("kr/law/") \
                            else "UNRESOLVED"
                elif len(hits) > 1:
                    kind, res = "EXTERNAL_UNRESOLVED", "AMBIGUOUS"
                elif r.extractor == "rule:name-work" and not re.search(r"(?:법|법률|령)$", r.name):
                    continue  # '심사기준에 따라' 같은 일반 낱말일 수 있다: 해석 못 한 이름만 참조는 남기지 않는다 (R5)
                else:
                    kind, res = "EXTERNAL_UNRESOLVED", "UNRESOLVED"
                    if looks_like_law(r.name) and r.name not in BARE_LAW and len(norm_title(r.name)) >= 3:
                        cur = conn.execute("INSERT INTO regulation.law_seed (name, origin, first_seen_work_id)"
                                           " VALUES (%s, 'reference', %s) ON CONFLICT DO NOTHING", (r.name, work_id))
                        st["seeds"] += cur.rowcount
                st["named"] += r.kind != "external"
            conn.execute(
                "INSERT INTO regulation.reference (work_id, source_pv_id, evidence_text, span_start, span_end, rel_type,"
                " target_kind, target_work_id, target_path, target_name, resolution, confidence, extractor) VALUES"
                " (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (work_id, pv["id"], r.evidence, r.start, r.end, r.rel_type, kind, tw, tpath, r.name, res,
                 r.confidence, r.extractor))
            st["refs"] += 1
            st["resolved" if res == "RESOLVED" else "unresolved"] += 1
    return st
