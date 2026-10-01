"""질의 분석 (spec 8.2-1): 기관·기간·기준일은 규칙, 질문 유형·검색어 확장은 LLM."""
import re
from dataclasses import dataclass, field

from reg.llm import ProviderError
from reg.qa.institutions import resolve_mention

TYPES = ["기한", "금액", "가능여부", "절차", "정의", "기타"]
SCHEMA = {"type": "object", "required": ["question_type", "terms"], "properties": {
    "question_type": {"type": "string", "enum": TYPES},
    "terms": {"type": "array", "items": {"type": "string"}, "maxItems": 6}}}
RE_DAYS = re.compile(r"(\d{1,3})\s*일\s*(?:이|가)?\s*(?:지났|경과|됐|되었|넘었|넘|지나)")
RE_WEEKS = re.compile(r"(\d{1,2})\s*주\s*(?:일)?\s*(?:이|가)?\s*(?:지났|경과|됐|되었|넘었|넘|지나)")
RE_DATE = re.compile(r"(\d{4})\s*(?:년|\.)\s*(\d{1,2})\s*(?:월|\.)\s*(\d{1,2})\s*(?:일|\.)?")

# 질문에 흔한 말 → 규정 본문에 쓰이는 말 (LLM 없이도 검색어를 넓힌다)
SYNONYMS = {
    "지출결의": ["정산", "증빙서 제출"], "출장비": ["여비"], "출장": ["여비"], "복명": ["출장복명서"],
    "연차": ["연가", "휴가"], "휴가": ["휴가"], "숙박비": ["숙박비", "실비"], "카드": ["법인카드", "신용카드"],
    "결과보고": ["결과보고서"], "월급": ["보수"], "급여": ["보수"], "퇴직금": ["퇴직급여"],
}

PROMPT = ("너는 한국 공공연구기관 내부규정 검색을 돕는다. 질문을 분류하고, 규정 본문에 실제로 쓰일 법한 검색어로 바꿔라.\n"
          "예) '지출결의' → '정산', '증빙 제출', '여비'. '출장비' → '여비'. 질문 유형은 기한/금액/가능여부/절차/정의/기타 중 하나.")


PATTERN = r"유형: (기한|금액|가능여부|절차|정의|기타)\n검색어: ([^\n]{2,80})"
FORMAT = "\n출력 형식(두 줄):\n유형: 기한|금액|가능여부|절차|정의|기타 중 하나\n검색어: 쉼표로 구분한 검색어 3~6개"


@dataclass
class Analysis:
    institution: str | None
    as_of: str | None
    question_type: str
    elapsed_days: int | None
    terms: list[str] = field(default_factory=list)


def analyze(llm, question: str) -> Analysis:
    days = None
    if m := RE_DAYS.search(question):
        days = int(m[1])
    elif m := RE_WEEKS.search(question):
        days = int(m[1]) * 7
    as_of = None
    if m := RE_DATE.search(question):
        as_of = f"{int(m[1]):04d}-{int(m[2]):02d}-{int(m[3]):02d}"
    qtype, terms = "기타", []
    if llm is not None:
        try:
            out = llm.regex([{"role": "system", "content": PROMPT + FORMAT}, {"role": "user", "content": question}],
                            PATTERN, max_tokens=120)
            m = re.fullmatch(PATTERN, out)
            qtype = m[1]
            terms = [] if m[2].strip() == "없음" else [t.strip() for t in m[2].split(",") if t.strip()][:6]
        except ProviderError:
            pass
    if days is not None:  # 경과 기간이 있으면 기한 판정 대상이다 (LLM 분류보다 우선)
        qtype = "기한"
    rule_terms = [t for word, ts in SYNONYMS.items() if word in question for t in ts]
    terms = list(dict.fromkeys(rule_terms + terms))[:8]
    return Analysis(resolve_mention(question), as_of, qtype, days, terms)
