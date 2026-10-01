"""답변 생성과 코드 검증 (spec 8.2-6·7, 2026-10-02: 계산 가능한 판정은 코드로)."""
import json
import re

from reg.llm import ProviderError
from reg.qa.evidence import Evidence

VERDICTS = ["미충족", "충족", "조건부", "판단불가"]
ANSWER_SCHEMA = {"type": "object", "required": ["결론", "근거", "설명", "확인_필요", "문의처"], "properties": {
    "결론": {"type": "string", "enum": VERDICTS},
    "근거": {"type": "array", "minItems": 1, "maxItems": 4, "items": {
        "type": "object", "required": ["id", "인용"],
        "properties": {"id": {"type": "string"}, "인용": {"type": "string", "maxLength": 160}}}},
    "설명": {"type": "string", "maxLength": 600},
    "확인_필요": {"type": "array", "items": {"type": "string", "maxLength": 200}, "maxItems": 3},
    "문의처": {"type": "string", "maxLength": 60}}}
SYSTEM = ("너는 공공연구기관 내부규정 안내자다. 반드시 주어진 근거(E1, E2…)의 문장만 사용해 한국어로 답한다.\n"
          "규칙: 1) 근거.인용에는 근거 본문에서 핵심 구절(80자 이내)을 글자 그대로 옮긴다. 2) 설명의 숫자는 근거에 있는 숫자만 쓴다.\n"
          "3) 결론은 질문자의 상황이 규정의 요건·기한을 충족하는지로 정한다(미충족/충족/조건부/판단불가).\n"
          "4) 근거만으로 판단할 수 없으면 판단불가. 5) 규정에 없는 용어(예: 지출결의)는 확인_필요에 적는다.\n"
          "6) 법적 판단이 아니라 규정 안내다.")
RE_DEADLINE = re.compile(r"(\d+)\s*(일|주일|주)\s*이내")
RE_NUM = re.compile(r"\d+(?:\.\d+)?")
BAD_OK = re.compile(r"넘|초과|지났|위반|늦")
BAD_NG = re.compile(r"문제없|문제가 없|충족합니다")


def _n(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def deadline_verdict(elapsed_days: int | None, quotes: list[str]) -> tuple[str, int] | None:
    if elapsed_days is None:
        return None
    for q in quotes:
        if m := RE_DEADLINE.search(q):
            limit = int(m[1]) * (7 if m[2].startswith("주") else 1)
            return ("미충족" if elapsed_days > limit else "충족", limit)
    return None


def verify(answer: dict, evidence: list[Evidence], question_numbers: set[str]) -> dict:
    by_id = {e.id: e for e in evidence}
    cites = answer.get("근거") or []
    exist = bool(cites) and all(c.get("id") in by_id for c in cites)
    quotes = exist and all(_n(c.get("인용")) and _n(c["인용"]) in _n(by_id[c["id"]].text) for c in cites)
    cited_nums = set(RE_NUM.findall(" ".join(f"{by_id[c['id']].title} {by_id[c['id']].label} {by_id[c['id']].text}"
                                             for c in cites if c.get("id") in by_id)))  # 조문 라벨(제27조)의 숫자도 근거
    nums = set(RE_NUM.findall(answer.get("설명", ""))) - question_numbers
    numbers = nums <= cited_nums
    verdict, expl = answer.get("결론"), answer.get("설명", "")
    consistent = not ((verdict == "충족" and BAD_OK.search(expl)) or (verdict == "미충족" and BAD_NG.search(expl)))
    problems = [k for k, ok in [("citation", exist), ("quote", quotes), ("number", numbers), ("consistency", consistent)]
                if not ok]
    return {"ok": not problems, "citations_exist": exist, "quotes_match": quotes, "numbers_match": numbers,
            "consistent": consistent, "problems": problems}


def _prompt(question: str, analysis, evidence: list[Evidence], problems: list[str] | None) -> list[dict]:
    ev = "\n\n".join(f"[{e.id}] {e.title} {e.label} (시행 {e.effective_from or '미상'}"
                     f"{', ' + e.rel if e.rel else ''})\n{e.text}" for e in evidence)
    user = f"질문: {question}\n질문 유형: {analysis.question_type}\n\n근거:\n{ev}"
    if problems:
        user += "\n\n이전 답변의 문제: " + ", ".join(problems) + " — 근거 본문을 글자 그대로 인용하고, 근거에 없는 숫자를 쓰지 말 것."
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


FORMAT = ("\n\n다음 형식으로만 답하라(각 항목 한 줄):\n결론: 미충족|충족|조건부|판단불가 중 하나\n"
          "근거: 사용한 근거 id(예: E1)\n인용: 근거 본문의 핵심 구절을 글자 그대로(80자 이내)\n"
          "설명: 질문자 상황에 대한 설명\n확인: 규정에 없어 확인이 필요한 점(없으면 없음)\n문의처: 소관부서")


def _pattern(ids: list[str]) -> str:
    return (r"결론: (미충족|충족|조건부|판단불가)\n근거: (" + "|".join(map(re.escape, ids)) + r")\n인용: ([^\n]{5,160})\n"
            r"설명: ([^\n]{10,500})\n확인: ([^\n]{2,200})\n문의처: ([^\n]{2,40})")


def _parse(text: str, pattern: str) -> dict:
    m = re.fullmatch(pattern, text)
    if m is None:
        raise ProviderError("LLM 응답이 형식에 맞지 않음")
    check = m[5].strip()
    return {"결론": m[1], "근거": [{"id": m[2], "인용": m[3].strip().strip('"“”\'')}], "설명": m[4].strip(),
            "확인_필요": [] if check in ("없음", "없음.") else [check], "문의처": m[6].strip()}


def _deadline_sentence(text: str) -> str | None:
    for sent in re.split(r"(?<=다\.)\s*", text):
        if RE_DEADLINE.search(sent):
            return re.sub(r"^[①-⑳\d.\s]+", "", sent).strip()[:160]
    return None


def _code_verdict(ans: dict, analysis, evidence: list[Evidence]) -> bool:
    """기한형 질문: 인용 근거에 기한이 없으면 리랭크 순위가 가장 높은 기한 조문으로 코드가 판정한다."""
    if analysis.question_type != "기한" or analysis.elapsed_days is None:
        return False
    by_id = {e.id: e for e in evidence}
    cited = [by_id[c["id"]] for c in ans["근거"] if c["id"] in by_id]
    target = next((e for e in cited if deadline_verdict(analysis.elapsed_days, [e.text])), None) or \
        next((e for e in evidence if e.role == "primary" and deadline_verdict(analysis.elapsed_days, [e.text])), None)
    if target is None:
        return False
    verdict, limit = deadline_verdict(analysis.elapsed_days, [target.text])
    if target.id not in {c["id"] for c in ans["근거"]}:
        ans["근거"].insert(0, {"id": target.id, "인용": _deadline_sentence(target.text) or target.text[:160]})
    ans["결론"] = verdict
    lead = (f"{target.title} {target.label}의 기한은 {limit}일 이내이고 질문 상황은 {analysis.elapsed_days}일이 지나 "
            f"{'기한을 넘겼습니다' if verdict == '미충족' else '기한 안입니다'}.")
    if verdict == "충족":
        lead = f"{target.title} {target.label}의 기한은 {limit}일 이내이며 질문 상황({analysis.elapsed_days}일째)은 기한 안입니다."
    ans["설명"] = lead + " " + ans["설명"]
    return True


def generate(llm, question: str, analysis, evidence: list[Evidence]) -> dict:
    qnums = set(RE_NUM.findall(question))
    pattern = _pattern([e.id for e in evidence])
    problems = None
    last_v = {"ok": False, "problems": []}
    for attempt in (1, 2):
        msgs = _prompt(question, analysis, evidence, problems)
        msgs[-1]["content"] += FORMAT
        try:
            ans = _parse(llm.regex(msgs, pattern, max_tokens=700), pattern)
        except ProviderError as e:
            kind = "llm_invalid_output" if "형식" in str(e) or "JSON" in str(e) else "llm_unavailable"
            return {"answer": None, "verification": {"ok": False, "problems": [kind]}, "attempts": attempt,
                    "verdict_source": None}
        source = "code" if _code_verdict(ans, analysis, evidence) else "llm"
        last_v = verify(ans, evidence, qnums)
        if last_v["ok"]:
            return {"answer": ans, "verification": last_v, "attempts": attempt, "verdict_source": source}
        problems = last_v["problems"]
    return {"answer": None, "verification": last_v, "attempts": 2, "verdict_source": None}
