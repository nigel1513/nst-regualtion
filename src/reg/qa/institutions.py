"""질문 속 기관 언급 → 기관 코드 (규칙). 애매하면 None (되묻기)."""
import re

ALIASES = {
    "NST": ["국가과학기술연구회", "과기연구회", "연구회", "NST"],
    "KASI": ["한국천문연구원", "천문연구원", "천문연", "KASI"],
    "KIST": ["한국과학기술연구원", "키스트", "KIST"],
    "ETRI": ["한국전자통신연구원", "전자통신연구원", "에트리", "ETRI"],
}


def resolve_mention(text: str) -> str | None:
    t = text.upper()
    found = set()
    pairs = sorted(((a, code) for code, al in ALIASES.items() for a in al), key=lambda x: -len(x[0]))
    for alias, code in pairs:
        # 다른 이름의 일부(KISTI 속 KIST, 학술연구회 속 연구회)는 기관 언급이 아니다. 뒤에는 조사가 붙을 수 있다
        tail = r"(?![A-Z0-9])" if alias.isascii() else ""
        pat = re.compile(r"(?<![A-Z0-9가-힣])" + re.escape(alias.upper()) + tail)
        if pat.search(t):
            found.add(code)
            t = pat.sub(" ", t)
    return found.pop() if len(found) == 1 else None
