"""질문 속 기관 언급 → 기관 코드 (규칙). 애매하면 None (되묻기)."""
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
        if alias.upper() in t:
            found.add(code)
            t = t.replace(alias.upper(), " ")
    return found.pop() if len(found) == 1 else None
