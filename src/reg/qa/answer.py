"""답변 생성과 코드 검증 (spec 8.2-6·7, 2026-10-02: 계산 가능한 판정은 코드로)."""
import re

from reg.platform.llm import ProviderError
from reg.qa.evidence import Evidence, sub_label

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
RE_DEADLINE = re.compile(r"(\d+)\s*(일|주일|주|개월|월)\s*이내")
RE_NUM = re.compile(r"\d+(?:\.\d+)?")
RE_QTY = re.compile(r"(\d+(?:\.\d+)?)\s*(주일|개월|만원|천원|원|일|주|월|년|회|시간|%|조|항|호)?")
BAD_OK = re.compile(r"기한을\s*넘|기한이\s*지났|기한을\s*지나|초과하였|위반|늦었")
QUOTE_MIN = 0.85  # 인용문 글자 중 원문 구간과 일치해야 하는 비율
RE_NEG = re.compile(r"아니|않|없|못")
BAD_NG = re.compile(r"문제없|문제가 없|충족합니다|기한\s*(?:내|안)에\s*있|기한\s*안입니다")


def _n(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def _limits(text: str) -> set:
    """본문의 'N일/주일/개월 이내' 기한. 일 단위로 바꾸고, 개월은 날짜 계산 없이는 비교할 수 없어 ('월', N)으로 둔다."""
    out = set()
    for m in RE_DEADLINE.finditer(text):
        n, unit = int(m[1]), m[2]
        out.add(("월", n) if unit in ("개월", "월") else n * (7 if unit.startswith("주") else 1))
    return out


def deadline_verdict(elapsed_days: int | None, quotes: list[str]) -> tuple[str, int | str] | None:
    """기한이 하나뿐일 때만 코드가 판정한다. 여러 기한(본문·단서)이 섞이면 판정하지 않는다.

    N개월은 달력에 따라 28N~31N일이므로 그 범위 밖일 때만 충족/미충족이고, 범위 안이면 조건부다."""
    if elapsed_days is None:
        return None
    for q in quotes:
        lims = _limits(q)
        if not lims:
            continue
        if len(lims) > 1:
            return None
        limit = next(iter(lims))
        if isinstance(limit, int):
            return ("미충족" if elapsed_days > limit else "충족", limit)
        n = limit[1]
        verdict = "충족" if elapsed_days <= 28 * n else "미충족" if elapsed_days > 31 * n else "조건부"
        return (verdict, f"{n}개월")
    return None


def _align(quote: str, text: str) -> str | None:
    """공백을 무시하고 인용문과 가장 잘 맞는 원문 구간을 찾는다. 충분히 일치하면 원문 그대로의 구간을 돌려준다.

    줄여 쓴 인용(중간 수식어 생략)은 받되, 문단을 넘거나 숫자·부정 표현(아니·않·없·못)이 달라지면 뜻이 바뀔 수
    있어 받지 않는다. 부정 표현은 구간이 끝나는 문장 끝까지 본다 ('지급하' + '지 아니한다')."""
    from difflib import SequenceMatcher

    nq = _n(quote)
    pos = [i for i, ch in enumerate(text) if not ch.isspace()]
    nt = "".join(text[i] for i in pos)
    if not nq or not nt:
        return None
    if (at := nt.find(nq)) >= 0:
        return text[pos[at]:pos[at + len(nq) - 1] + 1]
    width = 2 * len(nq) + 40
    best = (0.0, 0, 0)
    starts = {max(0, b.b - b.a) for b in SequenceMatcher(None, nq, nt, autojunk=False).get_matching_blocks()
              if b.size >= 3}
    for st in starts:  # 인용문 첫머리에 맞춘 창마다 겹치는 정도를 재고 가장 잘 맞는 창을 고른다
        win = nt[st:st + width]
        blocks = [b for b in SequenceMatcher(None, nq, win, autojunk=False).get_matching_blocks() if b.size >= 3]
        cov = sum(b.size for b in blocks) / len(nq)
        if blocks and cov > best[0]:
            best = (cov, st + blocks[0].b, st + blocks[-1].b + blocks[-1].size)
    cov, s, e = best
    if cov < QUOTE_MIN:
        return None
    span = nt[s:e]
    raw = text[pos[s]:pos[e - 1] + 1]
    tail = re.match(r"[^\n]{0,30}?(?:다\.|$)", text[pos[e - 1] + 1:], re.MULTILINE)
    if ("\n" in raw and "\n" not in quote) or RE_NUM.findall(span) != RE_NUM.findall(nq) or \
            len(RE_NEG.findall(span + _n(tail[0] if tail else ""))) != len(RE_NEG.findall(nq)):
        return None
    return raw


def _qty(text: str) -> set[tuple[str, str]]:
    return {(m[1], "주" if m[2] == "주일" else (m[2] or "")) for m in RE_QTY.finditer(text)}


def verify(answer: dict, evidence: list[Evidence], question_numbers: set[str],
           allowed_numbers: set[str] | None = None) -> dict:
    by_id = {e.id: e for e in evidence}
    cites = answer.get("근거") or []
    exist = bool(cites) and all(c.get("id") in by_id for c in cites)
    kept = []
    if exist:
        for c in cites:  # 모델이 줄여 쓴 인용은 원문 구간으로 바꿔 보여준다 (화면에는 항상 원문)
            span = _align(c.get("인용", ""), by_id[c["id"]].text)
            if span is not None:
                kept.append({**c, "인용": span})
    dropped = len(cites) - len(kept)
    quotes = exist and bool(kept)
    if kept:  # 원문과 맞는 인용이 하나라도 있으면 맞지 않는 인용만 뺀다
        answer["근거"] = cites = kept
    cited_text = " ".join(f"{by_id[c['id']].title} {by_id[c['id']].label} {by_id[c['id']].text}"
                          for c in cites if c.get("id") in by_id)  # 조문 라벨(제27조)의 숫자도 근거
    cited_qty = _qty(cited_text)
    cited_nums = {n for n, _ in cited_qty}
    expl_text = answer.get("설명", "")
    free = question_numbers | (allowed_numbers or set())
    # 'N일 이내' 같은 기한은 질문 속 숫자로 대신할 수 없다: 근거 본문(또는 주→일 환산)에 있어야 한다
    lims = {f"{x}일" for x in _limits(cited_text) if isinstance(x, int)} | \
        {f"{n}{'주' if u.startswith('주') else u}" for n, u in RE_DEADLINE.findall(cited_text)}
    deadlines_ok = all(f"{n}{'주' if u.startswith('주') else u}" in lims for n, u in RE_DEADLINE.findall(expl_text))
    plain_ok = all(n in free or (n, u) in cited_qty or (not u and n in cited_nums) or (u in ("조", "항", "호") and n in cited_nums)
                   for n, u in _qty(expl_text))
    numbers = deadlines_ok and plain_ok
    verdict, expl = answer.get("결론"), answer.get("설명", "")
    consistent = not ((verdict == "충족" and BAD_OK.search(expl)) or (verdict == "미충족" and BAD_NG.search(expl)))
    problems = [k for k, ok in [("citation", exist), ("quote", quotes), ("number", numbers), ("consistency", consistent)]
                if not ok]
    return {"ok": not problems, "citations_exist": exist, "quotes_match": quotes, "numbers_match": numbers,
            "consistent": consistent, "problems": problems, "dropped_citations": dropped}


def _prompt(question: str, analysis, evidence: list[Evidence], problems: list[str] | None) -> list[dict]:
    def hint(e: Evidence) -> str:   # 검색이 조 안에서 맞힌 항·호 (M7: 항 단위 근거)
        labels = [x for x in (sub_label(p) for p in e.matched_paths) if x]
        return f" · 질문과 맞는 부분: {', '.join(labels)}" if labels else ""

    ev = "\n\n".join(f"[{e.id}] {e.title} {e.label} (시행 {e.effective_from or '미상'}"
                     f"{', ' + e.rel if e.rel else ''}){hint(e)}\n{e.text}" for e in evidence)
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
    return {"결론": m[1], "근거": [{"id": m[2], "인용": re.sub(r"\s*\(?E\d+\)?$", "", m[3].strip()).strip('"“”\'')}], "설명": m[4].strip(),
            "확인_필요": [] if check in ("없음", "없음.") else [check], "문의처": m[6].strip()}


def _deadline_sentence(text: str) -> str | None:
    for sent in re.split(r"(?<=다\.)\s*", text):
        if RE_DEADLINE.search(sent):
            return re.sub(r"^[①-⑳\d.\s]+", "", sent).strip()[:160]
    return None


def _code_verdict(ans: dict, analysis, evidence: list[Evidence]) -> bool:
    """기한형 질문: 인용한 근거의 기한으로 코드가 판정한다. 인용 근거에 기한이 없으면 같은 규정의 주 근거 중
    순위가 가장 높은 기한 조문을 쓴다. 기한이 여럿이거나 개월 단위면 판정하지 않는다 (LLM 판정 유지)."""
    if analysis.question_type != "기한" or analysis.elapsed_days is None:
        return False
    by_id = {e.id: e for e in evidence}
    cited = [by_id[c["id"]] for c in ans["근거"] if c["id"] in by_id]
    target = next((e for e in cited if _limits(e.text)), None)
    if target is None:
        works = {e.work_id for e in cited}
        target = next((e for e in evidence if e.role == "primary" and e.work_id in works and _limits(e.text)), None)
    if target is None or (got := deadline_verdict(analysis.elapsed_days, [target.text])) is None:
        return False
    verdict, limit = got
    quote = _deadline_sentence(target.text) or target.text[:160]  # 판정 근거 문장은 코드가 원문에서 뽑는다
    ans["근거"] = [{"id": target.id, "인용": quote}] + [c for c in ans["근거"] if c["id"] != target.id]
    span = f"{limit}일" if isinstance(limit, int) else limit
    head = f"{target.title} {target.label}의 기한은 {span} 이내"
    if verdict == "미충족":
        lead = f"{head}이고 질문 상황은 {analysis.elapsed_days}일이 지나 기한을 넘겼습니다."
    elif verdict == "충족":
        lead = f"{head}이며 질문 상황({analysis.elapsed_days}일째)은 기한 안입니다."
    else:
        n = int(span.removesuffix("개월"))
        lead = (f"{head}입니다. {span}은 달에 따라 {28 * n}~{31 * n}일이어서 질문 상황({analysis.elapsed_days}일째)은 "
                "기산일과 달력 날짜로 확인해야 합니다.")
    # LLM이 다른 결론을 냈다면 그 설명은 코드 판정과 어긋나므로 쓰지 않는다
    ans["설명"] = lead if ans["결론"] != verdict else lead + " " + ans["설명"]
    ans["결론"] = verdict
    return True


def _derived_numbers(analysis, evidence: list[Evidence]) -> set[str]:
    """계산으로 나온 숫자(경과 일수, 'N주일'의 일수 환산)는 설명에 써도 된다."""
    out = {str(analysis.elapsed_days)} if analysis.elapsed_days is not None else set()
    for e in evidence:
        for x in _limits(e.text):
            out |= {str(x)} if isinstance(x, int) else {str(28 * x[1]), str(31 * x[1])}
    return out


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
        last_v = verify(ans, evidence, qnums, _derived_numbers(analysis, evidence))
        if last_v["ok"]:
            return {"answer": ans, "verification": last_v, "attempts": attempt, "verdict_source": source}
        problems = last_v["problems"]
    return {"answer": None, "verification": last_v, "attempts": 2, "verdict_source": None}


# ---------------------------------------------------------------- 일반 답변 (결론 없음)

GENERAL_SYSTEM = ("너는 공공연구기관 내부규정 안내자다. 주어진 근거(E1, E2…)만 읽고 질문에 바로 답하라. 무엇인지·누가·어떻게·"
                  "언제까지·얼마인지·어떤 조건인지를 쉬운 한국어 2~4문장으로 쓴다. 질문자의 상황을 판정하지 말고(충족·미충족 같은 "
                  "결론을 쓰지 않는다) 규정 내용을 알려 준다. 근거에 없는 내용·숫자는 쓰지 않는다. 설명에는 근거 번호를 쓰지 않는다. "
                  "인용에는 답의 핵심이 되는 근거 본문 한 문장을 글자 그대로(80자 이내) 복사하고 1~2개 든다.")
RE_EREF = re.compile(r"\s*[(\[](?:E\d+)[^)\]]*[)\]]|\s*\bE\d+\b")   # 설명 속 근거 번호 표기 "(E1)", "(E1: …)"


def _bigrams(s: str) -> set[str]:
    s = _n(s)
    return {s[i:i + 2] for i in range(len(s) - 1)}


def best_sentence(quote: str, text: str, min_overlap: float = 0.5) -> str | None:
    """근거 본문에서 인용과 두 글자 조각이 가장 많이 겹치는 문장(원문 그대로). 겹침이 min_overlap 미만이면 None."""
    qb = _bigrams(quote)
    best, score = None, 0.0
    for sent in re.split(r"(?<=다\.)\s+|\n", text or ""):
        sent = re.sub(r"^\s*(?:[①-⑳]|\d+\.|[가-하]\.)\s*", "", sent).strip()
        if len(sent) >= 8 and qb and (sc := len(qb & _bigrams(sent)) / len(qb)) > score:
            best, score = sent, sc
    return best if score >= min_overlap else None


def _general_pattern(ids: list[str]) -> str:
    alt = "|".join(map(re.escape, ids))
    return r"설명: ([^\n]{10,500})(?:\n근거: (?:" + alt + r")\n인용: [^\n]{5,160}){1,2}"


def explain(llm, question: str, analysis, evidence: list[Evidence]) -> dict:
    """일반 답변: 질문에 바로 답하는 2~4문장 + 원문 인용 1~2개, 결론 없음. generate와 같은 검증(인용 원문 대조·숫자)을
    거치고, 말을 바꿔 옮긴 인용은 그 근거에서 가장 비슷한 원문 문장으로 바꾼다. 두 번 실패하면 answer=None."""
    qnums = set(RE_NUM.findall(question))
    pattern = _general_pattern([e.id for e in evidence])
    by_id = {e.id: e for e in evidence}
    ev = "\n\n".join(f"[{e.id}] {e.title} {e.label} (시행 {e.effective_from or '미상'}"
                      f"{', ' + e.rel if e.rel else ''})\n{e.text}" for e in evidence)
    note, last_v = "", {"ok": False, "problems": []}
    for attempt in (1, 2):
        user = (f"질문: {question}\n\n근거:\n{ev}{note}\n\n다음 형식으로만 답하라:\n설명: 질문에 대한 답(2~4문장)\n"
                "근거: 사용한 근거 id(예: E1)\n인용: 근거 본문 한 문장을 글자 그대로(근거·인용 줄은 1~2번)")
        try:
            out = llm.regex([{"role": "system", "content": GENERAL_SYSTEM}, {"role": "user", "content": user}],
                            pattern, max_tokens=700)
        except ProviderError:
            return {"answer": None, "verification": {"ok": False, "problems": ["llm_unavailable"], "mode": "general"},
                    "attempts": attempt, "verdict_source": None}
        m = re.fullmatch(pattern, out)
        if m is None:
            return {"answer": None, "verification": {"ok": False, "problems": ["llm_invalid_output"], "mode": "general"},
                    "attempts": attempt, "verdict_source": None}
        cites = []
        for i, q in re.findall(r"\n근거: (E\d+)\n인용: ([^\n]+)", out):
            q = q.strip().strip('"“”\'')
            text = by_id[i].text
            if _align(q, text) is None and (near := best_sentence(q, text)):
                q = near
            if not any(c["id"] == i and c["인용"] == q for c in cites):
                cites.append({"id": i, "인용": q})
        ans = {"결론": None, "근거": cites, "설명": RE_EREF.sub("", m[1]).strip(), "확인_필요": [], "문의처": None}
        last_v = {**verify(ans, evidence, qnums, _derived_numbers(analysis, evidence)), "mode": "general"}
        if last_v["ok"]:
            return {"answer": ans, "verification": last_v, "attempts": attempt, "verdict_source": None}
        note = ("\n\n이전 답변의 문제: " + ", ".join(last_v["problems"]) +
                " — 근거 본문을 글자 그대로 인용하고, 근거에 없는 숫자를 쓰지 말 것.")
    return {"answer": None, "verification": last_v, "attempts": 2, "verdict_source": None}
