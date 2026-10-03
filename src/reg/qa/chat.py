"""규정 도우미 (서비스 UI v2 §5): 검색과 질의응답을 한 대화로 합친다.

흐름: 마스킹 → 후속 질문이면 앞 대화로 혼자 뜻이 통하는 질의로 바꾸기 → 범위(전체/기관 선택, 질문 속 기관 언급으로
좁히기) → 의도(조문 찾기 / 질문 / 여러 기관 비교) → 검색 카드(results)를 먼저 보내고 → 의도별로 답변·비교표 → 근거 →
후속 질문 → done. 기존 QA의 분석·하이브리드 검색·근거 확장(그래프)·EXAONE 생성·검증을 그대로 쓴다.

이벤트는 (종류, 데이터) 쌍으로 내보낸다. 종류: status · results · answer_delta · answer · table · citations ·
followups · done. results는 여러 번 올 수 있고 뒤의 것이 앞의 것을 바꾼다. 실패해도 이미 보낸 근거 카드는 남고 done은
반드시 온다. 모든 인용(quote)은 근거 본문 안에 글자 그대로 있는 구간이다 — 아니면 버린다 (Harvey식)."""
import json
import logging
import re
import time
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote as urlquote

from reg.platform.llm import ProviderError
from reg.qa.analyze import analyze
from reg.qa.answer import RE_NUM, _align, generate
from reg.qa.evidence import Evidence, expand, sub_label
from reg.qa.institutions import load_aliases
from reg.qa.mask import mask_pii
from reg.qa.service import MIN_SCORE, _db, _log, retrieve
from reg.search.citation import parse_citation

logger = logging.getLogger(__name__)

MAX_CONTEXT = 6        # 질의 바꾸기에 쓰는 앞 대화 메시지 수
MAX_TABLE = 8          # 비교표 기관 수 (추출은 기관마다 LLM 한 번)
CARD_LIMIT = 8
SNIPPET = 180
EXTRACT_WORKERS = 4

Event = tuple[str, dict]

# 여러 기관 비교 표현. '비교견적'(계약 용어)은 비교 요청이 아니다
RE_COMPARE = re.compile(r"다른\s*(?:기관|곳|연구원|연구소|데)|타\s*기관|기관\s*별|기관마다|여러\s*기관|각\s*기관|모든\s*기관|"
                        r"전체\s*기관|비교(?!\s*견적)")
# 질문 표현: 이것이 없고 번호 인용·규정명뿐이면 조문 찾기다
RE_QUESTION = re.compile(r"[?？]|나요|까요|가요|은요|는요|인가|인지|할까|되나|돼요|되요|어요|아요|해요|했는데|어떻게|어떤|언제|"
                         r"며칠|얼마|무엇|뭐|몇|가능|해야|하나|알려|설명|지났|넘었|궁금|따르면|대해|관해|기한|절차|방법")
RE_TITLE_TAIL = re.compile(r"(?:규정|규칙|지침|요령|세칙|기준|내규|정관|편람|법|법률|시행령|시행규칙)$")
# 앞 대화 없이는 뜻이 안 통하는 후속 질문
RE_FOLLOW = re.compile(r"^\s*(?:그럼|그러면|그건|그거|그것|거기|그\s|이\s|저\s|그리고|또|그런데|근데|다른|나머지|그때|그\s*경우|"
                       r"반대로|만약)|(?:은요|는요|도요|이면요|라면요|면요|도\s*(?:같나요|그런가요|알려\s*주세요))\s*[?？.]?\s*$")

REWRITE_SYSTEM = ("앞 대화를 참고해 마지막 질문을 앞 대화 없이도 뜻이 통하는 한 문장 질문으로 바꿔라. 앞 질문의 기관명·규정명·"
                  "주제 낱말을 글자 그대로 채워 넣고(다른 말로 바꾸지 말 것), 마지막 질문에 새로 나온 말은 그대로 둔다. "
                  "이미 완전한 질문이면 그대로 옮긴다.")
REWRITE_PATTERN = r"질문: ([^\n]{2,200})"
EXTRACT_SYSTEM = ("너는 기관별 규정 비교표를 만든다. 질문에 대한 이 기관 규정의 값을 20자 이내로 짧게 적고(예: 7일 이내, 30만원), "
                  "그 값이 나온 본문 구절을 글자 그대로 옮겨라. 본문에 답이 없으면 값과 인용 모두 '없음'이라고 적어라.")
EXTRACT_PATTERN = r"값: ([^\n]{1,40})\n인용: ([^\n]{2,160})"


# ---------------------------------------------------------------- 범위·의도

def mentions(text: str, aliases: dict[str, list[str]]) -> list[str]:
    """질문 속 기관 언급을 나온 순서대로 (resolve_mention과 같은 경계 규칙, 둘 이상도 돌려준다)."""
    t = (text or "").upper()
    found: dict[str, int] = {}
    pairs = sorted(((a, code) for code, al in aliases.items() for a in {*al, code} if a), key=lambda x: -len(x[0]))
    for alias, code in pairs:
        tail = r"(?![A-Z0-9])" if alias.isascii() else ""
        pat = re.compile(r"(?<![A-Z0-9가-힣])" + re.escape(alias.upper()) + tail)
        if m := pat.search(t):
            found.setdefault(code, m.start())
            t = pat.sub(lambda x: " " * len(x[0]), t)   # 위치를 지키며 지운다
    return sorted(found, key=found.get)


def _strip_mentions(text: str, aliases: dict[str, list[str]]) -> str:
    for alias in sorted({a for al in aliases.values() for a in al if a}, key=len, reverse=True):
        text = re.sub(r"(?<![A-Za-z0-9가-힣])" + re.escape(alias) + r"(?:의|에서|에)?", " ", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def is_lookup(query: str, aliases: dict[str, list[str]]) -> bool:
    """번호 인용("천문연 여비규정 27조")이나 규정명만 있고 질문 표현이 없으면 조문 찾기다 (생성 없음)."""
    if RE_QUESTION.search(query):
        return False
    if parse_citation(query, aliases) is not None:
        return True
    rest = _strip_mentions(query, aliases)
    return 2 <= len(rest) <= 40 and bool(RE_TITLE_TAIL.search(rest))


def strip_compare(query: str) -> str:
    """비교 요청 표현('다른 기관도', '기관별로' …)을 뺀 물음 (검색어·비교 항목 이름)."""
    q = re.sub("(?:" + RE_COMPARE.pattern + r")\S*(?:\s*(?:알려\s*주세요|어때요|같나요|요))?", " ", query)
    return re.sub(r"\s+", " ", q).strip(" ,.·")


def plan(query: str, scope: dict, aliases: dict[str, list[str]]) -> dict:
    """→ {intent, institutions, focus}. 범위가 '기관 선택'이면 선택이 질문 속 언급보다 우선한다.
    비교: 기관이 정해지지 않았거나(전체 범위), 둘 이상이거나, '다른 기관도'·'기관별'·'비교' 같은 말이 있을 때.
    institutions=None은 전체 기관이다. focus는 비교표 첫 줄에 둘 기관."""
    selected = [c for c in (scope.get("institutions") or []) if c in aliases] if scope.get("mode") == "institutions" else []
    insts = selected or mentions(query, aliases)
    if is_lookup(query, aliases):
        return {"intent": "lookup", "institutions": insts or None, "focus": insts[0] if len(insts) == 1 else None}
    if RE_COMPARE.search(query) or len(insts) != 1:
        many = len(insts) >= 2
        return {"intent": "comparison", "institutions": insts if many else None,
                "focus": insts[0] if len(insts) == 1 else None}
    return {"intent": "question", "institutions": insts, "focus": insts[0]}


RE_TAIL = re.compile(r"(?:은|는|도|의|에서|에|이|가)?\s*(?:요|어때요|어떤가요|같나요|알려\s*주세요)?\s*[?？.]?\s*$")
REWRITE_MIN_OVERLAP = 0.6   # 바꾼 질의의 두 글자 조각 중 앞 대화·마지막 질문에 있어야 하는 비율 (주제를 지어내지 않게)


def standalone(llm, messages: list[dict], aliases: dict[str, list[str]] | None = None) -> tuple[str, bool]:
    """마지막 사용자 말을 혼자 뜻이 통하는 질의로. 후속 질문 표현이 있을 때만 바꾼다. → (질의, 바꿨는지)

    흔한 꼴은 규칙으로: 기관만 바꾼 말("KBSI는요?")은 앞 질문의 기관을 바꾸고, 비교 요청만 있는 말("다른 기관도요?")은
    앞 질문에 붙인다. 나머지는 짧은 LLM 호출 한 번 — 앞 대화에 없는 말을 많이 지어내면 쓰지 않는다.
    LLM이 없거나 실패하면 바로 앞 사용자 질문을 앞에 붙인다."""
    ctx = messages[-MAX_CONTEXT:]
    users = [m["content"] for m in ctx if m["role"] == "user"]
    last = users[-1]
    if len(users) < 2 or not RE_FOLLOW.search(last):
        return last, False
    prev = users[-2]
    if aliases:
        rest = RE_TAIL.sub("", _strip_mentions(last, aliases)).strip(" ,.?？")
        new = mentions(last, aliases)
        if new and not rest:                                      # 기관만 바꿨다
            return f"{', '.join(aliases[c][0] for c in new)} {_strip_mentions(prev, aliases)}", True
        if not RE_TAIL.sub("", strip_compare(last)).strip(" ,.?？") and RE_COMPARE.search(last):   # 비교 요청만 있다
            return f"{prev} 다른 기관도", True
    if llm is not None:
        hist = "\n".join(f"{'질문' if m['role'] == 'user' else '답'}: {m['content'][:200]}" for m in ctx[:-1])
        try:
            out = llm.regex([{"role": "system", "content": REWRITE_SYSTEM},
                             {"role": "user", "content": f"앞 대화:\n{hist}\n\n마지막 질문: {last}\n\n출력 형식: 질문: …"}],
                            REWRITE_PATTERN, max_tokens=100)
            m = re.fullmatch(REWRITE_PATTERN, out)
            got = _bigrams(m[1]) if m else set()
            if got and len(got & _bigrams(hist + last)) / len(got) >= REWRITE_MIN_OVERLAP:
                return m[1].strip(), True
        except ProviderError:
            pass
    return f"{prev} {last}", True


# ---------------------------------------------------------------- 카드·인용

def _plain(highlight: str) -> tuple[str, list[list[int]]]:
    """'<mark>…</mark>' 강조 → (평문, [[시작, 끝]…])."""
    out, spans, pos = [], [], 0
    for part in re.split(r"(<mark>.*?</mark>)", highlight or "", flags=re.DOTALL):
        if part.startswith("<mark>"):
            inner = part[6:-7]
            spans.append([pos, pos + len(inner)])
            out.append(inner)
            pos += len(inner)
        elif part:
            out.append(part)
            pos += len(part)
    return "".join(out), spans


def _window(text: str, spans: list[list[int]], width: int = SNIPPET) -> tuple[str, list[list[int]]]:
    if len(text) <= width:
        return text, spans
    start = max(0, (spans[0][0] if spans else 0) - 30)
    end = min(len(text), start + width)
    cut = text[start:end]
    pre = "…" if start else ""
    out = [[s - start + len(pre), min(e, end) - start + len(pre)] for s, e in spans if s >= start and s < end]
    return pre + cut + ("…" if end < len(text) else ""), out


def href(work_id: str, path: str | None, as_of: str | None = None) -> str:
    """웹 규정 보기 링크 (apps/web workHref와 같은 꼴): /regulations/{work}?a={조}[&as_of=]#{경로}."""
    base = "/regulations/" + "/".join(urlquote(p, safe="") for p in work_id.split("/"))
    if not path:
        return base + (f"?as_of={as_of}" if as_of else "")
    art = path.split(".")[0]
    return base + f"?a={urlquote(art, safe='')}" + (f"&as_of={as_of}" if as_of else "") + f"#{urlquote(path, safe='')}"


def _title(h: dict) -> str | None:
    """색인에 규정명 대신 규정 id가 들어간 경우(kr/reg/기관/이름)는 이름 부분만."""
    t = h.get("title")
    return t.rsplit("/", 1)[-1] if t and t.startswith("kr/") else t


def card(h: dict, as_of: str | None = None) -> dict:
    """검색 결과(조 묶음) → 조문 카드: 기관, 규정, 조 라벨, 맞은 항·호, 강조 발췌, 링크."""
    art = h.get("article_path") or h["path"].split(".")[0]
    matches = h.get("matches") or []
    hl = next((m["highlight"] for m in matches if m.get("highlight")), None)
    if hl:
        snippet, spans = _window(*_plain(hl))
    else:
        snippet, spans = _window(re.sub(r"\s+", " ", h.get("text") or ""), [])
    return {"id": f"{h['version_id']}|{art}", "institution": {"code": h.get("institution"), "name": h.get("institution_name")},
            "work_id": h["work_id"], "version_id": h["version_id"], "title": _title(h), "article_path": art,
            "label": h.get("path_label") or h.get("label"),
            "matched": [{"path": m["path"], "label": sub_label(m["path"]) or m.get("label")} for m in matches
                        if m["path"] != art],
            "snippet": snippet, "highlights": spans, "effective_from": h.get("effective_from"),
            "kind": h.get("family"), "href": href(h["work_id"], (matches[0]["path"] if matches else art), as_of),
            "score": h.get("rerank_score", h.get("score"))}


def cards(found: dict, as_of: str | None = None, works: set[str] | None = None, limit: int = CARD_LIMIT) -> list[dict]:
    """번호 조회 결과를 앞에, 하이브리드 결과를 뒤에 (같은 조는 한 번)."""
    out, seen = [], set()
    for x in found.get("lookup") or []:
        art = x.get("article_path") or x["path"].split(".")[0]
        head = (x.get("article_text") or "").split("\n", 1)[0]
        label = head if head.startswith(_art_label(x.get("label"))) and len(head) <= 60 else \
            _art_label(x.get("full_label")) or x.get("label")
        h = {**x, "article_path": art, "path_label": label, "matches": [{"path": x["path"], "label": x.get("label")}],
             "text": x.get("text") or x.get("article_text")}
        out.append(card(h, as_of))
    for h in found.get("hits") or []:
        out.append(card(h, as_of))
    res = []
    for c in out:
        if c["id"] in seen or (works is not None and c["work_id"] not in works):
            continue
        seen.add(c["id"])
        res.append(c)
    return res[:limit]


def _n(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def verbatim(quote: str, text: str) -> str | None:
    """인용을 원문 구간으로: 줄여 쓴 인용은 원문 구간으로 바꾸고(answer._align, 숫자·부정 표현이 같아야 함),
    결과가 원문 안에 글자 그대로 없으면 None (버린다)."""
    if not quote or not text:
        return None
    span = quote if quote in text else _align(quote, text)
    return span if span and span in text else None


def _units(conn, version_id: str, art: str) -> list[dict]:
    return conn.execute(
        "SELECT pv.path, pv.text FROM regulation.version_provision vp"
        " JOIN regulation.provision_version pv ON pv.id = vp.provision_version_id"
        " WHERE vp.work_version_id = %s AND (pv.path = %s OR pv.path LIKE %s) ORDER BY vp.ord",
        (version_id, art, art + ".%")).fetchall()


def locate(units: list[dict], quote: str, fallback: str) -> str:
    """인용이 들어 있는 가장 깊은 조항 경로 (항 번호 표시 '①'은 빼고 본다). 여러 조항에 걸치면 첫머리가 있는 조항."""
    q = _n(re.sub(r"^\s*[①-⑳]\s*|^\s*\d+\.\s*|^\s*[가-하]\.\s*", "", quote))
    best = None
    for key in (q, q[:15]):
        for u in units:
            if key and key in _n(u["text"]) and (best is None or u["path"].count(".") > best.count(".")):
                best = u["path"]
        if best:
            return best
    return fallback


def _art_label(label: str | None) -> str:
    m = re.search(r"(제\d+조(?:의\d+)?|별표\s*\d+|별지\s*\d+)", label or "")
    return m[1] if m else (label or "")


def _work_meta(conn, work_ids: list[str]) -> dict[str, dict]:
    rows = conn.execute("SELECT w.id, i.code, i.name FROM regulation.work w"
                        " LEFT JOIN regulation.institution i ON i.id = w.institution_id WHERE w.id = ANY(%s)",
                        (list(set(work_ids)),)).fetchall()
    return {r["id"]: {"code": r["code"], "name": r["name"]} for r in rows}


def citation(conn, n: int, e: Evidence, quote: str, meta: dict, as_of: str | None) -> dict | None:
    """근거 하나 → 인용 카드. quote가 근거 본문에 글자 그대로 없으면 None."""
    span = verbatim(quote, e.text)
    if span is None:
        return None
    art = e.path.split(".")[0]
    path = locate(_units(conn, e.version_id, art), span, e.path)
    label = " ".join(x for x in (e.title, _art_label(e.label), sub_label(path)) if x)
    inst = meta.get(e.work_id) or {"code": None, "name": None}
    return {"n": n, "institution": inst, "work_id": e.work_id, "version_id": e.version_id, "title": e.title,
            "path": path, "label": label, "quote": span, "href": href(e.work_id, path, as_of)}


# ---------------------------------------------------------------- 답변

def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=다\.)\s+|(?<=[.!?])\s+(?=[가-힣A-Za-z0-9「(])", (text or "").strip())
    return [p.strip() for p in parts if p.strip()]


def _qty(s: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?\s*(?:일|주|개월|월|년|원|만원|천원|%|시간|회)", s))


def answer_event(ans: dict, cites: list[dict]) -> dict:
    """QA 답변(결론·설명·확인·문의처) → 문장별 근거 번호. 문장 속 수량(7일 등)이 인용에 있으면 그 인용을, 아니면 첫 인용."""
    sents = []
    for s in _sentences(ans.get("설명", "")):
        q = {x.replace(" ", "") for x in _qty(s)}
        hit = [c["n"] for c in cites if q and q & {x.replace(" ", "") for x in _qty(c["quote"])}]
        sents.append({"text": s, "cites": hit or ([cites[0]["n"]] if cites else [])})
    return {"conclusion": ans.get("결론"), "sentences": sents, "explanation": ans.get("설명", ""),
            "checks": ans.get("확인_필요") or [], "contact": ans.get("문의처")}


# ---------------------------------------------------------------- 비교

def _has_table(conn, name: str) -> bool:
    return conn.execute("SELECT to_regclass(%s) AS r", (name,)).fetchone()["r"] is not None


def _bigrams(s: str) -> set[str]:
    s = _n(s)
    return {s[i:i + 2] for i in range(len(s) - 1)}


def compare_cells(conn, query: str) -> list[dict] | None:
    """regulation.compare_cell(기관 비교 트랙)이 있으면 질문과 가장 비슷한 비교 항목의 칸들. 표나 맞는 항목이 없으면 None.
    열 이름은 설계(UI v2 §4)를 따르되 다를 수 있어 information_schema로 확인하고, 모르는 꼴이면 쓰지 않는다."""
    if not _has_table(conn, "regulation.compare_cell"):
        return None
    cols = {r["column_name"] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = 'regulation'"
        " AND table_name = 'compare_cell'").fetchall()}
    item = next((c for c in ("item_label", "item_name", "item", "item_key") if c in cols), None)
    pv = next((c for c in ("provision_version_id", "pv_id", "evidence_pv_id") if c in cols), None)
    inst = "i.code" if "institution_id" in cols else "cc.institution" if "institution" in cols else None
    if not (item and pv and inst and {"value", "quote"} <= cols):
        return None
    join = " JOIN regulation.institution i ON i.id = cc.institution_id" if inst == "i.code" else ""
    rows = conn.execute(f"SELECT cc.{item}::text AS item, {inst} AS institution, cc.value::text AS value,"
                        f" cc.quote::text AS quote, cc.{pv} AS pv_id FROM regulation.compare_cell cc{join}"
                        " WHERE cc.value IS NOT NULL").fetchall()
    qb = _bigrams(query)
    score: dict[str, float] = {}
    for r in rows:
        ib = _bigrams(r["item"])
        if ib:
            score[r["item"]] = len(ib & qb) / len(ib)
    if not score or (best := max(score, key=score.get)) is None or score[best] < 0.5:
        return None
    return [r for r in rows if r["item"] == best]


def _cell_evidence(conn, pv_id) -> dict | None:
    return conn.execute(
        "SELECT pv.path, pv.text, wv.id AS version_id, wv.work_id, wv.title FROM regulation.provision_version pv"
        " JOIN regulation.version_provision vp ON vp.provision_version_id = pv.id"
        " JOIN regulation.work_version wv ON wv.id = vp.work_version_id WHERE pv.id = %s"
        " ORDER BY (wv.version_state = 'CURRENT') DESC LIMIT 1", (pv_id,)).fetchone()


def extract_value(llm, question: str, h: dict) -> tuple[str, str] | None:
    """조문 하나에서 짧은 값과 원문 인용. 인용이 원문에 글자 그대로 없거나 값의 숫자가 인용에 없으면 None."""
    text = h.get("text") or ""
    user = f"질문: {question}\n기관: {h.get('institution_name')}\n규정: {_title(h)} {h.get('path_label') or ''}\n\n본문:\n{text[:3000]}"
    try:
        out = llm.regex([{"role": "system", "content": EXTRACT_SYSTEM}, {"role": "user", "content": user}],
                        EXTRACT_PATTERN, max_tokens=140)
    except ProviderError:
        return None
    m = re.fullmatch(EXTRACT_PATTERN, out)
    if not m or m[1].strip().startswith("없음"):
        return None
    value = m[1].strip()
    span = verbatim(m[2].strip().strip('"“”\''), text)
    if span is None or not set(RE_NUM.findall(value)) <= set(RE_NUM.findall(span)):
        return None
    return value, span


def _pick_per_institution(hits: list[dict], focus: str | None, limit: int) -> list[dict]:
    best: dict[str, dict] = {}
    for h in hits:
        if h.get("institution") and h["institution"] not in best:
            best[h["institution"]] = h
    order = sorted(best, key=lambda c: (c != focus, -best[c].get("rerank_score", best[c].get("score") or 0)))
    return [best[c] for c in order[:limit]]


# ---------------------------------------------------------------- 후속 질문

FOLLOW_BY_TYPE = {"기한": "기한을 넘기면 어떻게 되나요?", "금액": "한도를 넘으면 어떻게 하나요?",
                  "절차": "필요한 서류는 무엇인가요?", "가능여부": "예외가 인정되는 경우가 있나요?",
                  "정의": "이 용어가 쓰이는 다른 조문도 알려 주세요"}


def followups(intent: str, *, qtype: str | None = None, top: dict | None = None, extra: list[str] | None = None,
              compared: list[dict] | None = None) -> list[str]:
    out: list[str] = list(extra or [])
    if intent == "lookup" and top:
        out += [f"{top['title']} {_art_label(top['label'])} 내용을 쉽게 설명해 주세요", "다른 기관의 같은 조항은 어떻게 되어 있나요?",
                f"{top['title']}의 다른 조문도 보여 주세요"]
    elif intent == "question":
        out += [FOLLOW_BY_TYPE.get(qtype or "", "관련 예외 조항이 있나요?"), "다른 기관은 어떻게 정하고 있나요?",
                "담당 부서는 어디인가요?"]
    elif intent == "comparison":
        vals = [r for r in compared or [] if r.get("value")]
        if vals:
            out.append(f"{vals[0]['institution']['name']} 규정 원문을 자세히 보여 주세요")
        out += ["기관마다 다른 이유가 있나요?", "가장 많은 기관이 쓰는 기준은 무엇인가요?"]
    return list(dict.fromkeys(x for x in out if x))[:3]


# ---------------------------------------------------------------- 범위

def scope_works(conn, scope: dict) -> set[str] | None:
    """scope.work_ids·topic → 검색 결과를 걸러낼 규정 id 집합 (없으면 None = 거르지 않음).
    주제는 regulation.work_topic(기관 비교 트랙)이 있을 때만 쓴다."""
    works = set(scope.get("work_ids") or [])
    if scope.get("topic") and _has_table(conn, "regulation.work_topic"):
        works |= {r["work_id"] for r in conn.execute(
            "SELECT work_id FROM regulation.work_topic WHERE topic = %s", (scope["topic"],)).fetchall()}
    return works or None


# ---------------------------------------------------------------- 대화 한 턴

def chat(db, deps: dict, messages: list[dict], scope: dict | None = None, as_of: str | None = None,
         conversation_id: str | None = None, log: bool = True) -> Iterator[Event]:
    """한 턴을 이벤트로 흘려보낸다. db: 연결 또는 풀(단계마다 잠깐 빌린다). log=False면 ops.qa_log에 쓰지 않는다."""
    t0 = time.monotonic()
    scope = scope or {"mode": "all"}
    cid = conversation_id or uuid.uuid4().hex
    st = {"first_results_ms": None, "status": "error", "retrieved": [], "answer": None, "verification": {},
          "release_id": None, "intent": None, "query": None, "institution": None, "as_of": as_of, "note": None}

    def ms() -> int:
        return int((time.monotonic() - t0) * 1000)

    def results(cs: list[dict]) -> Event:
        if st["first_results_ms"] is None:
            st["first_results_ms"] = ms()
        return "results", {"cards": cs}

    msgs = [{"role": m["role"], "content": mask_pii((m.get("content") or "").strip())} for m in messages
            if m.get("role") in ("user", "assistant")]
    try:
        if not msgs or msgs[-1]["role"] != "user" or not msgs[-1]["content"]:
            raise ValueError("마지막 메시지는 사용자 질문이어야 합니다")
        with _db(db) as conn:
            aliases = load_aliases(conn)
            works = scope_works(conn, scope)
            conn.commit()
        query, rewritten = standalone(deps.get("llm"), msgs, aliases)
        p = plan(query, scope, aliases)
        st.update(intent=p["intent"], query=query, institution=p["focus"])
        names = {c: al[0] for c, al in aliases.items()}
        yield "status", {"stage": "understand", "label": "질문을 이해했습니다", "conversation_id": cid,
                         "intent": p["intent"], "query": query, "rewritten": rewritten,
                         "institutions": [{"code": c, "name": names.get(c)} for c in p["institutions"] or []],
                         "scope_mode": "institutions" if p["institutions"] else "all"}
        run = {"lookup": _lookup, "question": _question, "comparison": _comparison}[p["intent"]]
        yield from run(db, deps, query, p, aliases, works, as_of, st, results)
    except Exception as e:  # 실패해도 done은 보낸다 (이미 보낸 근거 카드는 화면에 남는다)
        logger.exception("chat turn failed")
        st.update(status="error", note=f"{type(e).__name__}: {e}"[:300])
    if log and msgs and msgs[-1]["role"] == "user":
        try:
            with _db(db) as conn:
                res = {"status": st["status"], "institution": st["institution"], "as_of": st["as_of"],
                       "answer": st["answer"], "verification": st["verification"], "release_id": st["release_id"]}
                turn = sum(m["role"] == "user" for m in msgs)
                st["qa_id"] = _log(conn, msgs[-1]["content"], res, None, ms(), deps.get("llm_model"), st["retrieved"],
                                   {"chat": {"conversation_id": cid, "turn": turn, "intent": st["intent"],
                                             "query": st["query"], "scope": scope,
                                             "first_results_ms": st["first_results_ms"]}})
        except Exception:
            logger.exception("chat log failed")
    yield "done", {"conversation_id": cid, "qa_id": st.get("qa_id"), "intent": st["intent"], "status": st["status"],
                   "note": st["note"], "first_results_ms": st["first_results_ms"], "latency_ms": ms()}


def _retrieved(hits: list[dict]) -> list[dict]:
    return [{"version_id": h["version_id"], "path": h["path"], "score": h.get("rerank_score", h["score"])} for h in hits]


def _filter(hits: list[dict], works: set[str] | None) -> list[dict]:
    return hits if works is None else [h for h in hits if h["work_id"] in works]


def _lookup(db, deps, query, p, aliases, works, as_of, st, results) -> Iterator[Event]:
    yield "status", {"stage": "search", "label": "조문을 찾고 있습니다"}
    inst = p["institutions"][0] if p["institutions"] and len(p["institutions"]) == 1 else None
    found, hits = retrieve(deps, query, inst, as_of, aliases, size=30 if works else 10)
    cs = cards(found, as_of, works)
    if p["institutions"] and len(p["institutions"]) > 1:
        cs = [c for c in cs if c["institution"]["code"] in p["institutions"] or c["kind"] != "reg"]
    yield results(cs)
    st.update(status="lookup" if cs else "not_found", release_id=found.get("release_id"),
              retrieved=_retrieved(_filter(hits, works)))
    yield "followups", {"items": followups("lookup", top=cs[0] if cs else None)}


def _question(db, deps, query, p, aliases, works, as_of, st, results) -> Iterator[Event]:
    inst = p["institutions"][0]
    llm = deps.get("llm")
    yield "status", {"stage": "search", "label": "관련 규정을 찾고 있습니다"}
    size = 30 if works else 10
    # 질의 분석(LLM)과 첫 검색을 함께 돌려 근거 카드를 먼저 보낸다
    with ThreadPoolExecutor(1) as ex:
        fut = ex.submit(analyze, llm, query, aliases)
        found0, hits0 = retrieve(deps, query, inst, as_of, aliases, size=size)
        first = cards(found0, as_of, works)
        yield results(first)
        a = fut.result()
    as_of0, as_of = as_of, as_of or a.as_of
    st["as_of"] = as_of
    if a.terms or as_of != as_of0:
        found, hits = retrieve(deps, " ".join([query, *a.terms]), inst, as_of, aliases, size=size)
        cs = cards(found, as_of, works)
        if [c["id"] for c in cs] != [c["id"] for c in first]:
            yield results(cs)
    else:
        found, hits = found0, hits0
    hits = _filter(hits, works)
    st.update(release_id=found.get("release_id"), retrieved=_retrieved(hits))
    top = hits[0].get("rerank_score", 1.0) if hits else 0.0
    if not hits or (found["reranked"] and top < MIN_SCORE):
        st.update(status="not_found", note="관련 규정을 찾지 못했습니다")
        yield "followups", {"items": followups("question", qtype=a.question_type)}
        return
    yield "status", {"stage": "read", "label": "조문을 읽고 있습니다"}
    with _db(db) as conn:
        evidence = expand(conn, hits, as_of=as_of, release_id=found["release_id"], related=deps.get("related"))
        conn.commit()
    yield "status", {"stage": "write", "label": "답변을 쓰고 있습니다"}
    gen = generate(llm, query, a, evidence) if llm else \
        {"answer": None, "verification": {"ok": False, "problems": ["llm_unavailable"]}, "verdict_source": None}
    st["verification"] = {**gen["verification"], "verdict_source": gen.get("verdict_source")}
    ans = gen["answer"]
    cites: list[dict] = []
    if ans:
        by_id = {e.id: e for e in evidence}
        with _db(db) as conn:
            meta = _work_meta(conn, [e.work_id for e in evidence])
            for c in ans["근거"]:
                if c["id"] in by_id and (x := citation(conn, len(cites) + 1, by_id[c["id"]], c["인용"], meta, as_of)):
                    cites.append(x)
            conn.commit()
    if ans and cites:
        ev = answer_event(ans, cites)
        yield "answer_delta", {"text": ev["explanation"]}   # 생성기가 스트리밍을 하지 않아 검증된 설명을 한 번에
        yield "answer", ev
        yield "citations", {"items": cites}
        st.update(status="answered", answer=ans)
    else:
        st.update(status="evidence_only", note="자동 설명을 만들지 못해 근거 조문만 보여드립니다")
    related = [e for e in evidence if e.role != "primary"]
    extra = [f"{related[0].title} {_art_label(related[0].label)}도 알려 주세요"] if related else []
    yield "followups", {"items": followups("question", qtype=a.question_type, extra=extra)}


def _comparison(db, deps, query, p, aliases, works, as_of, st, results) -> Iterator[Event]:
    llm = deps.get("llm")
    yield "status", {"stage": "search", "label": "기관별 규정을 찾고 있습니다"}
    terms = analyze(None, query).terms            # 규칙 동의어만 (LLM 호출 없이)
    question = strip_compare(query) or query
    q = " ".join([question, *terms])
    insts = p["institutions"]
    if insts:   # 고른 기관마다 검색 (기관 수가 적다)
        with ThreadPoolExecutor(min(len(insts), EXTRACT_WORKERS)) as ex:
            got = list(ex.map(lambda c: retrieve(deps, q, c, as_of, aliases, size=5, kind="reg"), insts))
        found = {"hits": [h for f, _ in got for h in f["hits"]], "lookup": [], "release_id": got[0][0].get("release_id"),
                 "reranked": all(f["reranked"] for f, _ in got)}
    else:       # 전체 기관: 한 번 검색해 기관마다 1위 조를 고른다
        found, _ = retrieve(deps, q, None, as_of, aliases, size=40, kind="reg")
    hits = _filter([h for h in found["hits"] if h.get("family") == "reg"], works)
    picked = _pick_per_institution(hits, p["focus"], MAX_TABLE)
    yield results([card(h, as_of) for h in picked])
    st.update(release_id=found.get("release_id"), retrieved=_retrieved(picked))
    if not picked:
        st.update(status="not_found", note="비교할 규정을 찾지 못했습니다")
        yield "followups", {"items": followups("comparison")}
        return
    yield "status", {"stage": "compare", "label": "기관별 값을 뽑고 있습니다"}
    rows, cites = [], []
    with _db(db) as conn:
        cells = compare_cells(conn, question)
        names = {c: al[0] for c, al in aliases.items()}
        if cells is not None:
            for r in cells:
                ev = _cell_evidence(conn, r["pv_id"]) if r["pv_id"] else None
                span = verbatim(r["quote"], ev["text"]) if ev else None
                if not span:
                    continue
                n = len(cites) + 1
                cites.append({"n": n, "institution": {"code": r["institution"], "name": names.get(r["institution"])},
                              "work_id": ev["work_id"], "version_id": ev["version_id"], "title": ev["title"],
                              "path": ev["path"], "label": " ".join(x for x in (ev["title"], sub_label(ev["path"])) if x),
                              "quote": span, "href": href(ev["work_id"], ev["path"], as_of)})
                rows.append({"institution": cites[-1]["institution"], "value": r["value"], "cite": n})
        conn.commit()
    source = "compare_cell" if cells is not None else "extracted"
    if cells is None:
        got = []
        if llm is not None:
            with ThreadPoolExecutor(EXTRACT_WORKERS) as ex:
                got = list(ex.map(lambda h: extract_value(llm, question, h), picked))
        with _db(db) as conn:
            for h, g in zip(picked, got or [None] * len(picked)):
                inst = {"code": h.get("institution"), "name": h.get("institution_name")}
                if g is None:
                    rows.append({"institution": inst, "value": None, "cite": None, "title": _title(h),
                                 "href": card(h, as_of)["href"]})
                    continue
                value, span = g
                art = h.get("article_path") or h["path"].split(".")[0]
                path = locate(_units(conn, h["version_id"], art), span, art)
                n = len(cites) + 1
                cites.append({"n": n, "institution": inst, "work_id": h["work_id"], "version_id": h["version_id"],
                              "title": _title(h), "path": path,
                              "label": " ".join(x for x in (_title(h), _art_label(h.get("path_label")),
                                                            sub_label(path)) if x),
                              "quote": span, "href": href(h["work_id"], path, as_of)})
                rows.append({"institution": inst, "value": value, "cite": n, "title": _title(h),
                             "href": cites[-1]["href"]})
            conn.commit()
    yield "table", {"item": question, "source": source, "focus": p["focus"], "rows": rows}
    if cites:
        yield "citations", {"items": cites}
    st.update(status="compared" if cites else "evidence_only", answer={"table": rows},
              verification={"ok": bool(cites), "source": source, "rows": len(rows), "values": len(cites)})
    yield "followups", {"items": followups("comparison", compared=rows)}


# ---------------------------------------------------------------- 전송 형식

def sse(event: str, data: dict) -> str:
    """Server-Sent Events 한 덩어리: 'event: …\\ndata: {json}\\n\\n' (data는 한 줄 JSON)."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def collect(events: Iterator[Event]) -> list[dict]:
    return [{"event": e, "data": d} for e, d in events]
