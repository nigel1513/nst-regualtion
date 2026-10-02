"""질문 속 기관 언급 → 기관 코드 (규칙). 애매하면 None (되묻기).

기관 이름표는 DB(regulation.institution: 정식명·약칭 aliases·코드)에서 읽는다 (overview §2.8).
약칭은 config/sources/alio.yaml에 적고 수집(load_institutions)이 DB에 반영한다."""
import re


def load_aliases(conn) -> dict[str, list[str]]:
    """활성 기관의 {코드: [정식명, 약칭…, 코드]}. 비활성 기관은 검색할 규정이 없으므로 빼고 되묻는다."""
    rows = conn.execute("SELECT code, name, aliases FROM regulation.institution WHERE active ORDER BY id").fetchall()
    return {r["code"]: list(dict.fromkeys([r["name"], *(r["aliases"] or []), r["code"]])) for r in rows}


def resolve_mention(text: str, aliases: dict[str, list[str]]) -> str | None:
    t = text.upper()
    found = set()
    pairs = sorted(((a, code) for code, al in aliases.items() for a in al if a), key=lambda x: -len(x[0]))
    for alias, code in pairs:
        # 다른 이름의 일부(KISTI 속 KIST, 학술연구회 속 연구회)는 기관 언급이 아니다. 뒤에는 조사가 붙을 수 있다
        tail = r"(?![A-Z0-9])" if alias.isascii() else ""
        pat = re.compile(r"(?<![A-Z0-9가-힣])" + re.escape(alias.upper()) + tail)
        if pat.search(t):
            found.add(code)
            t = pat.sub(" ", t)
    return found.pop() if len(found) == 1 else None
