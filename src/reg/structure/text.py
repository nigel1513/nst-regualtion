import re
import unicodedata
from datetime import date

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
    """PDF 줄바꿈 이어붙이기. 원문 띄어쓰기 정보가 없어서 문서 안 어절 사전으로 추정한다.

    사전 = 각 줄의 안쪽 어절(줄 첫·끝 어절은 잘린 조각일 수 있어 뺀다).
    한글-한글 경계: 합친 어절이 사전에 있으면 붙이고, 앞 조각이 완전한 어절이면 띄우고, 그 밖에는 붙인다.
    """

    def __init__(self, lines: list[str]):
        self.vocab: set[str] = set()
        for ln in lines:
            toks = ln.split()
            self.vocab.update(t for t in toks[1:-1] if len(t) > 1)  # 한 글자 어절은 띄어쓰기 근거로 약하다

    def join(self, prev: str, nxt: str) -> str:
        if not prev:
            return nxt
        if not nxt:
            return prev
        a, b = prev[-1], nxt[0]
        if not (_hangul(a) and _hangul(b)):
            return prev + " " + nxt
        last, first = prev.split()[-1], nxt.split()[0]
        if last + first in self.vocab:
            return prev + nxt
        if last in self.vocab:
            return prev + " " + nxt
        return prev + nxt
