"""law.go.kr 링크 (spec §3A.6). 형식이 바뀌면 이 파일만 고친다. 2026-10-02 실제 접속으로 모두 200 확인.

한글·영숫자는 그대로 두고 그 밖의 문자(공백, 가운뎃점, 괄호 등)만 퍼센트 인코딩한다.
OC 키는 어떤 링크에도 넣지 않는다.
"""
import re
from datetime import date
from urllib.parse import quote

BASE = "https://www.law.go.kr"
_ART = re.compile(r"^a(\d+)(?:-(\d+))?(?:\.|$)")


def _seg(s: str) -> str:
    return "".join(c if ("가" <= c <= "힣") or (c.isascii() and c.isalnum()) else quote(c, safe="") for c in s)


def law_page(name: str) -> str:
    return f"{BASE}/법령/{_seg(name)}"


def admrul_page(name: str) -> str:
    return f"{BASE}/행정규칙/{_seg(name)}"


def page_for(family: str, name: str) -> str:
    return law_page(name) if family == "law" else admrul_page(name)


def article_label(path: str | None) -> str | None:
    m = _ART.match(path or "")
    return f"제{int(m[1])}조" + (f"의{int(m[2])}" if m[2] else "") if m else None


def jo_code(path: str | None) -> str | None:
    m = _ART.match(path or "")
    return f"{int(m[1]):04d}{int(m[2] or 0):02d}" if m else None


def article_page(family: str, name: str, path: str) -> str | None:
    label = article_label(path)
    return f"{page_for(family, name)}/{label}" if label else None


def law_edition_page(name: str, promulgation_no: str, promulgated_on: date) -> str:
    return f"{law_page(name)}/({_seg(promulgation_no)},{promulgated_on:%Y%m%d})"


def _drf(family: str, key: str, kind: str) -> str:
    return (f"{BASE}/DRF/lawService.do?target=law&MST={key}&type={kind}" if family == "law"
            else f"{BASE}/DRF/lawService.do?target=admrul&ID={key}&type={kind}")


def drf_xml(family: str, key: str) -> str:
    return _drf(family, key, "XML")


def drf_html(family: str, key: str) -> str:
    return _drf(family, key, "HTML")


def annex_page(family: str, seq: str, owner_key: str) -> str:
    if family == "law":
        return f"{BASE}/LSW/lsBylInfoP.do?bylSeq={seq}&lsiSeq={owner_key}"
    return f"{BASE}/LSW/admRulBylInfoP.do?bylSeq={seq}&admRulSeq={owner_key}&admFlag=0"


def file_url(path: str | None) -> str | None:
    return f"{BASE}{path}" if path else None
