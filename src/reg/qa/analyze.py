"""질의 분석 (spec 8.2-1): 기관·기간·기준일은 규칙, 질문 유형·검색어 확장은 LLM."""
import re
from dataclasses import dataclass, field
from datetime import date

from reg.platform.llm import ProviderError
from reg.qa.institutions import resolve_mention

TYPES = ["기한", "금액", "가능여부", "절차", "정의", "기타"]
SCHEMA = {"type": "object", "required": ["question_type", "terms"], "properties": {
    "question_type": {"type": "string", "enum": TYPES},
    "terms": {"type": "array", "items": {"type": "string"}, "maxItems": 6}}}
RE_DAYS = re.compile(r"(?<![\d월])(?<!월\s)(\d{1,3})\s*일\s*(?:이|가)?\s*(?:지났|경과|됐|되었|넘었|넘|지나)")
RE_WEEKS = re.compile(r"(\d{1,2})\s*주\s*(?:일)?\s*(?:이|가)?\s*(?:지났|경과|됐|되었|넘었|넘|지나)")
RE_MD = re.compile(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일")
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


# ---------------------------------------------------------------- 답변 방식 (일반 / 판정)
# 기본은 일반 답변(규정 내용을 바로 알려 주고 결론은 없음). 판정(충족·미충족…)은 질문자가 자기 상황(지난 날수·쓴 돈·한 일·
# 할 일)을 말하고 그것이 괜찮은지·가능한지·위반인지 물을 때만. 규칙이 먼저이고, 애매할 때만 LLM에 한 번 묻는다. 모르면 일반.

# 자기 상황(한 일·할 일·쓴 돈). '받으면'·'입으면' 같은 가정은 상황이 아니다
RE_FACT = re.compile(r"넘겨\s*썼|넘겼|초과\s*(?:해|했|지출|사용|결제)|썼는데|썼어요|썼습니다|썼고|지출했|결제했|사용했|"
                     r"(?:안|못)\s*냈|(?:안|못)\s*했|아직|했는데|했고|했어요|했습니다|받았는데|받았어요|다녀왔는데|"
                     r"(?:하|쓰|가|받|내|사)려고|려는데|할\s*예정|예정인데|"
                     r"\d[\d,]*\s*(?:만\s*)?원(?:을|이|어치)?\s*(?:썼|지출|사용|결제|냈)")
# 괜찮은지·가능한지·위반인지 묻는 말
RE_ASK_OK = re.compile(r"괜찮|문제\s*(?:가\s*)?(?:없|되|있)|가능한가|가능할까|가능하나|가능해|가능합니까|되나요|될까요|돼요\s*[?？]|"
                       r"되요\s*[?？]|되나\s*[?？]|위반|늦었|받을\s*수\s*있|할\s*수\s*있나|불이익|징계")
# 할 일을 말하며 허락을 묻는 말 ('데리고 출근해도 되나요', '써도 돼요?') — 이것만으로 판정
RE_PERMIT = re.compile(r"[어아여해워써와가져쳐]도\s*(?:되|돼|괜찮)")
# 규정 내용을 묻는 말 (무엇·누가·어떻게·언제까지·얼마…)
RE_INFO = re.compile(r"뭐|무엇|무슨|이란|란\s*[?？]|알려|설명|어떻게|어떤|누가|누구|어디|언제|며칠|얼마|몇|목적|대상|종류|절차|방법|"
                     r"있나요|있어|기한은|한도는|기준은|상한은")
RE_ASKS = re.compile(r"[?？]|나요|까요|가요|니까|는지|ㄴ지|인지|래요|해\s*$|야\s*$")
MODE_SYSTEM = ("질문자가 자기의 구체적 상황(지난 날수, 쓴 금액, 이미 한 일이나 하려는 일)을 말하고 그것이 규정에 맞는지(괜찮은지·"
               "가능한지·위반인지) 묻는가? 그렇다면 '판단', 규정 내용 자체(무엇·누가·어떻게·기한·금액)를 묻는다면 '일반'이라고만 답하라.")
MODE_PATTERN = r"판단|일반"


def answer_mode(question: str, elapsed_days: int | None = None, llm=None) -> str:
    """→ 'general'(일반 답변, 결론 없음) | 'judgment'(충족·미충족·조건부·판단불가 판정)."""
    q = question or ""
    fact = elapsed_days is not None or bool(RE_FACT.search(q))
    if RE_PERMIT.search(q) or (fact and (elapsed_days is not None or RE_ASK_OK.search(q) or not RE_ASKS.search(q))):
        return "judgment"
    if not fact and not RE_ASK_OK.search(q):
        return "general"
    if not fact and RE_INFO.search(q):             # '며칠 받을 수 있나요' — 가능 여부가 아니라 내용을 묻는다
        return "general"
    if llm is not None:                             # 상황+일반 물음, 또는 상황 없이 가능 여부만: 애매하다
        try:
            out = llm.regex([{"role": "system", "content": MODE_SYSTEM}, {"role": "user", "content": q}],
                            MODE_PATTERN, max_tokens=4)
            return "judgment" if out.strip() == "판단" else "general"
        except ProviderError:
            pass
    return "general"


@dataclass
class Analysis:
    institution: str | None
    as_of: str | None
    question_type: str
    elapsed_days: int | None
    terms: list[str] = field(default_factory=list)
    mode: str = "general"        # answer_mode: general | judgment


def analyze(llm, question: str, aliases: dict[str, list[str]] | None = None) -> Analysis:
    """aliases: institutions.load_aliases(conn). 없으면 기관을 찾지 않는다."""
    days = None
    if m := RE_DAYS.search(question):
        days = int(m[1])
    elif m := RE_WEEKS.search(question):
        days = int(m[1]) * 7
    elif len(md := RE_MD.findall(question)) >= 2:  # '9월 20일에 끝났고 오늘이 9월 25일' → 5일
        try:
            (m1, d1), (m2, d2) = md[0], md[-1]
            diff = (date(2001, int(m2), int(d2)) - date(2001, int(m1), int(d1))).days
            days = diff if 0 < diff <= 366 else None
        except ValueError:
            pass
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
    return Analysis(resolve_mention(question, aliases) if aliases else None, as_of, qtype, days, terms,
                    answer_mode(question, days, llm))
