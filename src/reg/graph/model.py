"""그래프 모델의 순수 함수: 단위 라벨, 전체 라벨("여비규정 제27조 제1항"), 정의 조항의 용어 (spec 2026-10-03 §1.1)."""
import re
import unicodedata

UNIT_LABELS = {"article": "Article", "paragraph": "Paragraph", "item": "Item", "subitem": "Subitem",
               "annex": "Annex", "form": "Form", "supplement": "Supplement", "supp_article": "SuppArticle",
               "chapter": "Chapter", "section": "Section"}
CONTEXT_UNITS = ("chapter", "section")


def node_label(unit: str, path: str) -> str:
    """단위의 그래프 라벨. PostgreSQL은 별지 서식도 unit='annex'(경로 form…)로 두므로 경로로 Form을 가른다."""
    if unit == "annex" and path.startswith("form"):
        return "Form"
    return UNIT_LABELS.get(unit, "")
  # 전체 라벨·용어 사용에서 빼는 문맥 단위
REF_RELS = ("BASIS", "DELEGATION", "IMPLEMENTS", "MUTATIS", "EXCEPTION", "CITATION")

# "출장"이란 …을 말한다 / “고시금액”이라 함은 …을 말한다. 약칭 정의 '(이하 "법"이라 한다)'는 '말한다'가 없어 걸리지 않는다
RE_TERM = re.compile(r"[“\"‘'「]\s*([^”\"’'」\n]{1,30}?)\s*[”\"’'」]\s*(?:이)?(?:란|라\s?함은|라고\s?함은)\s*"
                     r"((?:(?![“\"‘'「][^”\"’'」\n]{1,30}[”\"’'」]\s*(?:이)?(?:란|라\s?함은|라고\s?함은))[^\n]){1,600}?"
                     r"말(?:한다|하고|하며|함))")


def unit_label(unit: str, label: str) -> str:
    """조항 번호 표기를 전체 라벨용으로: ① → 제1항, 3. → 제3호, 4의2. → 제4호의2, 가. → 가목."""
    label = (label or "").strip()
    if unit == "paragraph" and label and all(unicodedata.numeric(ch, None) is not None for ch in label):
        return f"제{int(sum(unicodedata.numeric(ch) for ch in label))}항"
    if unit == "item" and (m := re.fullmatch(r"(\d+)(?:의(\d+))?\.?", label)):
        return f"제{m[1]}호" + (f"의{m[2]}" if m[2] else "")
    if unit == "subitem" and (m := re.fullmatch(r"([가-힣])\.?", label)):
        return f"{m[1]}목"
    return label


def full_label(title: str, chain: list[tuple[str, str]]) -> str:
    """chain: 최상위 → 자신 순서의 (unit, number_label). 장·절은 문맥이라 뺀다."""
    parts = [unit_label(u, lab) for u, lab in chain if u not in CONTEXT_UNITS and lab]
    return " ".join([title, *parts]).strip()


def is_definition_article(unit: str, heading: str | None) -> bool:
    return unit == "article" and "정의" in (heading or "")


def extract_terms(text: str) -> list[tuple[str, str]]:
    """정의 문장에서 (용어, 정의문)."""
    out, seen = [], set()
    for m in RE_TERM.finditer(text or ""):
        name = m[1].strip()
        if len(name) < 2 or name in seen:
            continue
        seen.add(name)
        out.append((name, m[0].strip()))
    return out


def uses_terms(text: str, names: list[str]) -> list[str]:
    """그 본문이 쓰는 용어 (두 글자 이상)."""
    return [n for n in names if len(n) >= 2 and n in (text or "")]
