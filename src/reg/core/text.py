import gzip
import re
import unicodedata
from datetime import date
from functools import lru_cache
from pathlib import Path

_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\u200b﻿]")
_WS = re.compile(r"[ \t　\xa0]+")
NOTE = re.compile(r"<(?:개정|신설|본조신설|전문개정|제목개정|일부개정|삭제|타법개정)[^<>]*>"
                  r"|\[(?:본조신설|제목개정|전문개정|본조개정|종전|시행일)[^\[\]]*\]"
                  r"|<\s*'?\d{2,4}\s*\.[^<>]*>")
_DOT = re.compile(r"(?<!\d)('?\d{2}|\d{4})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})")
_YMD8 = re.compile(r"(?<!\d)(\d{4})(\d{2})(\d{2})(?!\d)")
KO_DATE = re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")


def clean(s: str) -> str:
    s = unicodedata.normalize("NFC", s or "")
    s = _CTRL.sub("", s)
    return _WS.sub(" ", s).strip()


def split_notes(s: str) -> tuple[str, list[str]]:
    notes = NOTE.findall(s)
    return clean(NOTE.sub(" ", s)), notes


def _mk(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_dot_date(s: str) -> date | None:
    m = _DOT.search(s or "")
    if m:
        y = m[1].lstrip("'")
        year = int(y) if len(y) == 4 else (1900 + int(y) if int(y) >= 50 else 2000 + int(y))
        return _mk(year, int(m[2]), int(m[3]))
    m = _YMD8.search(s or "")
    if m:
        return _mk(int(m[1]), int(m[2]), int(m[3]))
    m = KO_DATE.search(s or "")
    return _mk(int(m[1]), int(m[2]), int(m[3])) if m else None


def _hangul(c: str) -> bool:
    return "가" <= c <= "힣"


class Joiner:
    """PDF 줄바꿈 이어붙이기. 원문 띄어쓰기 정보가 없어서 어절 사전으로 추정한다 (M6-6).

    사전 = 패키지 사전(HWP 원문 어절 빈도) + 이 문서 각 줄의 안쪽 어절(줄 첫·끝 어절은 잘린 조각일 수 있어 뺀다).
    한글-한글 경계에서 앞 끝 어절 a, 뒤 첫 어절 b, 합친 ab에 대해
      1) ab가 사전에 있고 a나 b가 사전에 없으면 → 붙인다 (낱말 중간에서 줄이 바뀜)
      2) a와 b가 모두 사전에 있고 ab가 드물면 → 띄운다
      3) ab가 사전에 있으면 → 붙인다
      4) a가 조사·어미로 끝나고 b가 사전에 있으면 → 띄운다
      5) 그 밖에는 붙인다
    실측(150개 PDF, 9,374 경계): 오류율 36.5% → 3.3%.
    """

    def __init__(self, lines: list[str], lex: dict[str, int] | None = None):
        self.lex = lexicon() if lex is None else lex
        self.vocab: dict[str, int] = {}
        for ln in lines:
            for t in ln.split()[1:-1]:
                if len(t) > 1:  # 한 글자 어절은 띄어쓰기 근거로 약하다
                    w = _strip_word(t)
                    self.vocab[w] = self.vocab.get(w, 0) + 1

    def _f(self, w: str) -> int:
        return self.lex.get(w, 0) + self.vocab.get(w, 0)

    def join(self, prev: str, nxt: str) -> str:
        if not prev:
            return nxt
        if not nxt:
            return prev
        if not (_hangul(prev[-1]) and _hangul(nxt[0])):
            return prev + " " + nxt
        last, first = _strip_word(prev.split()[-1]), _strip_word(nxt.split()[0])
        fa, fb, fab = self._f(last), self._f(first), self._f(last + first)
        if fab >= 2 and (fa == 0 or fb == 0):
            return prev + nxt
        if fa >= 1 and fb >= 1 and fab < max(1, min(fa, fb) // 10):
            return prev + " " + nxt
        if fab >= 1:
            return prev + nxt
        if _WORD_END.search(last) and fb >= 1:
            return prev + " " + nxt
        return prev + nxt


# ---- M6-6: 글리프 정리 · 자간 띄움 · 줄 잇기 사전 ----

# 한컴 문서가 쓰는 사용자 정의 영역(PUA) 문자. 보기용 PDF에서도 글꼴이 없어 네모로 보이므로 뜻이 분명한 것만 바꾼다 (R3).
PUA_MAP = {
    "\U000f0852": "“", "\U000f0853": "”",                       # HWP 큰따옴표 (NST "(이하“연구회”라 한다)")
    "\U0000f09e": "·", "\U000f02ea": "·",                       # 가운뎃점 (설립·운영)
    "\U0000f06f": "□", "\U0000f0fe": "☑", "\U0000f0a1": "○",    # Wingdings 체크·글머리표
    "\U0000f0a7": "▪", "\U0000f06d": "❍",
    "\U000f0099": "~", "\U000f012b": "", "\U000f0036": "→", "\U000f03c5": "□",
}
# 서식의 밑줄·괘선을 그리는 PUA 문자열 (HWP U+F0800~F08FF, KIST PDF U+F000). 세 개 이상 이어지면 지운다
PUA_RUN = re.compile(r"[\U000f0800-\U000f08ff\U0000f000]{3,}")
_SPACED_LINE = re.compile(r"^(?:[가-힣] ){2,}[가-힣]$")
_WORD_END = re.compile(r"(?:다|고|며|여|서|에게|에서|으로|로|를|을|의|는|은|에|와|과|및|등|또는|하는|되는|한|된|할|될"
                       r"|하며|하고|하여|따라|위하여|대하여|관하여|경우|때)$")


def normalize_glyphs(s: str) -> str:
    """PUA 글리프를 뜻이 분명한 문자로 바꾸고 괘선 문자열을 지운다. KIST PDF의 U+F000은 짝이 맞으면 따옴표다."""
    s = PUA_RUN.sub(" ", s or "")
    for k, v in PUA_MAP.items():
        if k in s:
            s = s.replace(k, v)
    if "\U0000f000" in s:
        parts = s.split("\U0000f000")
        if len(parts) % 2 == 1:  # 짝수 개
            s = "".join(p + ("“" if i % 2 == 0 else "”") for i, p in enumerate(parts[:-1])) + parts[-1]
        else:
            s = s.replace("\U0000f000", " ")
    return s


def despace_line(s: str) -> str:
    """'소 액 구 매 신 청 서'처럼 한 글자씩 띄운 줄(서식 제목·자간 넓힘)을 붙인다. 줄 전체가 그럴 때만."""
    return s.replace(" ", "") if _SPACED_LINE.match(s) else s


def _strip_word(t: str) -> str:
    return re.sub(r"[^가-힣A-Za-z0-9]", "", t)


@lru_cache(maxsize=1)
def lexicon() -> dict[str, int]:
    """띄어쓰기가 정확한 HWP 원문에서 모은 어절 빈도 (reg quality build-lexicon). 파일이 없으면 빈 사전."""
    path = Path(__file__).parent / "data" / "lexicon.tsv.gz"
    if not path.exists():
        return {}
    out = {}
    for ln in gzip.decompress(path.read_bytes()).decode("utf-8").splitlines():
        w, _, n = ln.partition("\t")
        out[w] = int(n)
    return out
