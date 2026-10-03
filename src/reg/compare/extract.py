"""비교값 추출 (spec §4): 기관의 그 주제 규정 안에서 하이브리드 검색 → EXAONE 정규식 줄 형식으로 짧은 값 + 인용.

인용이 근거 조문 원문에 (공백을 무시하고) 그대로 있을 때만 값을 받는다. 숫자 값(기간·금액)은 같은 값이 인용 안에도
있어야 한다. 받을 후보가 없으면 '규정 없음'(absent) 칸을 만든다.

후보는 조항 단위 색인 문서(reg-provisions)에서 찾고 소속 조(article_key)로 묶는다. LLM에는 조 전체 본문을 주고,
인용이 들어 있는 가장 깊은 단위(항·호·목)를 근거 위치(path, pv_id)로 삼는다."""
import re
from dataclasses import asdict, dataclass, field

from reg.compare.config import Item
from reg.compare.normalize import fragments, normalize, snap, squash, value_supported
from reg.index.mapping import PIPELINE
from reg.index.service import base_filters, bm25_query
from reg.platform.llm import ProviderError

CANDIDATES = 100         # 하이브리드 후보 (검색 서비스와 같게)
RERANK_TOP = 40
ARTICLES = 4             # LLM에 보여 줄 조 수
ARTICLE_CHARS = 1800     # 조 하나를 프롬프트에 넣을 때 자르는 길이 (인용 검증은 전체 본문으로)
UNITS = ["article", "paragraph", "item", "subitem", "annex"]
SOURCE = ["pv_id", "work_id", "version_id", "title", "base_path", "path", "article_path", "article_key", "unit", "label",
          "text", "article_text", "context", "window", "ord", "institution"]
SYSTEM = ("너는 공공연구기관 내부규정에서 기준값을 찾아 옮기는 도우미다. 주어진 조문(C1, C2…)만 보고 답한다.\n"
          "규칙: 1) 값은 짧게 쓴다(예: 7일, 50,000원, 3개월, 있음). 2) 인용에는 값이 들어 있는 구절을 조문 본문에서 "
          "글자 그대로(띄어쓰기 포함) 옮긴다. 줄이거나 바꾸지 않는다. 3) 질문에 맞는 내용이 조문에 없으면 근거를 없음으로 한다.\n"
          "4) 다른 규정이나 법령을 따른다고만 적혀 있으면(예: '공무원 여비 규정에 따른다') 값에 그 내용을 짧게 적는다.\n"
          "5) 별표의 표는 칸이 풀려 한 줄로 이어져 있을 수 있다. 표에서 값을 찾았으면 그 숫자가 들어 있는 짧은 구절"
          "(예: '정액 25,000')을 그대로 인용한다. 6) 있음/없음을 묻는 질문은 그 절차·의무를 정한 조문이 있으면 있음이다.")
FORMAT = ("\n\n다음 형식으로만 답하라(각 항목 한 줄):\n근거: 사용한 조문 번호(C1 등) 또는 없음\n"
          "값: 짧은 값(30자 이내, 근거가 없으면 없음)\n인용: 값이 들어 있는 조문 구절을 글자 그대로(120자 이내, 근거가 없으면 없음)")
PENALTY = {"exact": 0.0, "fragment": 0.05, "aligned": 0.15, "table": 0.3}   # 인용을 받은 방법별 신뢰도 감점
MIN_RERANK = 0.02        # 리랭크 점수가 이보다 낮은 조는 후보에서 뺀다 (bge-reranker, 관련 없는 조)


@dataclass
class Unit:
    pv_id: int | None
    path: str
    unit: str
    text: str


@dataclass
class Candidate:
    work_id: str
    version_id: str
    title: str
    article_path: str
    text: str                       # 조 전체 본문 (머리 + 항·호·목)
    units: list[Unit] = field(default_factory=list)
    score: float = 0.0


@dataclass
class Cell:
    topic: str
    item: str
    institution_code: str
    method: str                      # llm | absent
    work_id: str | None = None
    version_id: str | None = None
    pv_id: int | None = None
    path: str | None = None
    value: str | None = None
    value_norm: str | None = None
    quote: str | None = None
    confidence: float | None = None
    title: str | None = None         # 표시·점검용 (저장하지 않음)
    note: str | None = None          # 받지 않은 이유 (점검용)

    def row(self) -> dict:
        d = asdict(self)
        d.pop("title"), d.pop("note")
        return d


def _search(os, body: dict, pipeline: str | None = None) -> list[dict]:
    res = os.search(body, pipeline=pipeline) if pipeline else os.search(body)
    return res["hits"]["hits"]


def candidates(os, embedder, reranker, item: Item, work_ids: list[str], k: int = ARTICLES) -> list[Candidate]:
    """그 기관·주제 규정(work_ids)의 현행 조항에서 항목 질의로 찾은 조 상위 k개."""
    if not work_ids:
        return []
    flt = base_filters(unit=UNITS) + [{"terms": {"work_id": work_ids}}]
    bm25 = bm25_query(item.query, flt)
    try:
        vec = embedder.embed([item.query])[0]
        hits = _search(os, {"size": CANDIDATES, "_source": SOURCE, "query": {"hybrid": {"queries": [
            bm25, {"knn": {"embedding": {"vector": vec, "k": CANDIDATES, "filter": {"bool": {"filter": flt}}}}}]}}},
            PIPELINE)
    except ProviderError:
        hits = _search(os, {"size": CANDIDATES, "_source": SOURCE, "query": bm25})
    units = [{**h["_source"], "score": h["_score"] or 0.0} for h in hits]
    if reranker and units:
        top = units[:RERANK_TOP]
        try:
            for i, s in reranker.rerank(item.ask, [f"{u.get('title') or ''} {u.get('context') or ''}\n"
                                                   f"{u.get('article_text') or u.get('text') or ''}"[:1500] for u in top]):
                top[i]["rerank"] = s
            units = sorted(top, key=lambda u: -u.get("rerank", -1.0))
            units = [u for u in units if u.get("rerank", 0.0) >= MIN_RERANK] or units[:1]
        except ProviderError:
            pass
    order: list[str] = []
    best: dict[str, float] = {}
    for u in units:
        key = u["article_key"]
        if key not in best:
            order.append(key)
            best[key] = u.get("rerank", u["score"])
    keys = order[:k]
    return [c for c in (_article(os, key, best[key]) for key in keys) if c is not None]


def _article(os, key: str, score: float) -> Candidate | None:
    docs = [h["_source"] for h in _search(os, {"size": 500, "_source": SOURCE,
                                               "query": {"bool": {"filter": [{"term": {"article_key": key}}]}},
                                               "sort": [{"ord": "asc"}, {"window": "asc"}]})]
    if not docs:
        return None
    top = next((d for d in docs if d["base_path"] == d["article_path"] and d.get("window", 0) <= 1), docs[0])
    merged: dict[str, Unit] = {}
    for d in docs:                                   # 긴 단위는 창(#n)으로 나뉘어 있다: 다시 잇는다
        u = merged.setdefault(d["base_path"], Unit(d.get("pv_id"), d["base_path"], d["unit"], ""))
        u.text += d.get("text") or ""
    text = top.get("article_text") or "\n".join(u.text for u in merged.values())
    return Candidate(top["work_id"], top["version_id"], top.get("title") or "", top["article_path"], text,
                     list(merged.values()), score)


def _pattern(n: int) -> str:
    ids = "|".join(f"C{i}" for i in range(1, n + 1))
    return rf"근거: ({ids}|없음)\n값: ([^\n]{{1,40}})\n인용: ([^\n]{{1,200}})"


def _prompt(item: Item, cands: list[Candidate], problem: str | None) -> list[dict]:
    ev = "\n\n".join(f"[C{i}] {c.title}\n{c.text[:ARTICLE_CHARS]}" for i, c in enumerate(cands, 1))
    user = f"질문: {item.ask}\n\n조문:\n{ev}"
    if problem:
        user += f"\n\n이전 답의 문제: {problem}"
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user + FORMAT}]


_TRIM = re.compile(r"^[\s\"'“”‘’「」『』<>*]+|[\s\"'“”‘’「」『』<>*]+$")
_NOTE = re.compile(r"\s*[(<\[〈](?:개정|신설|본조신설|전문개정|제목개정|삭제)[^)>\]〉]*[)>\]〉]\s*$")


def _clean(q: str) -> str:
    """모델이 덧붙인 따옴표·강조(**)·끝의 개정 주석(원문 본문에는 없다)을 뗀다."""
    q = (q or "").replace("**", "")
    prev = None
    while prev != q:
        prev, q = q, _NOTE.sub("", _TRIM.sub("", q))
    return q


_NUMBER = re.compile(r"\d[\d,]*")


def resolve_quote(quote: str, value: str, text: str, table: bool = False) -> tuple[str, str] | None:
    """(원문에 그대로 있는 인용, 방법). 방법: exact(그대로) · fragment('…'로 줄인 인용의 한 조각) · aligned(거의 그대로 —
    원문 구간으로 바꿈) · table(별표: 칸이 풀린 표를 모델이 다시 엮은 인용 → 값 숫자가 든 원문 조각). 아니면 None."""
    if squash(quote) and squash(quote) in squash(text):
        return quote, "exact"
    if (frag := verbatim(quote, value, text)) is not None:
        return frag, "fragment"
    if (span := snap(quote, text)) is not None:
        return span, "aligned"
    if table and (num := _NUMBER.search(value or "")):
        frag = next((f for f in fragments(quote, text) if num[0] in squash(f) and len(squash(f)) > len(num[0])), None)
        if frag is not None:
            return frag, "table"
    return None


_ELLIPSIS = re.compile(r"\s*(?:\.\.\.+|…+|⋯+|중략)\s*")


def verbatim(quote: str, value: str, text: str) -> str | None:
    """'A … B'처럼 줄여 쓴 인용: 조각이 모두 원문에 순서대로 있으면, 값이 든 조각(없으면 가장 긴 조각)만 인용으로 쓴다.
    저장하는 인용은 언제나 원문에 그대로 있는 구절이다."""
    parts = [p for p in _ELLIPSIS.split(quote) if len(squash(p)) >= 4]
    if len(parts) < 2:
        return None
    nt, at = squash(text), 0
    for p in parts:
        at = nt.find(squash(p), at)
        if at < 0:
            return None
        at += len(squash(p))
    nv = squash(value)
    return next((p for p in parts if nv and nv in squash(p)), max(parts, key=lambda p: len(squash(p))))


def locate(quote: str, c: Candidate) -> Unit | None:
    """인용이 들어 있는 가장 깊은 단위. 여러 단위에 걸치면 조 자체."""
    nq = squash(quote)
    nq_body = re.sub(r"^(?:[①-⑳]|\d+\.|[가-힣]\.)", "", nq)   # 항·호 번호 표기는 단위 본문에 없다
    hits = [u for u in c.units if nq_body and nq_body in squash(u.text)]
    if hits:
        return max(hits, key=lambda u: (u.path.count("."), len(u.path)))
    return next((u for u in c.units if u.path == c.article_path), None)


def in_bounds(value: str, item: Item) -> bool:
    if item.norm != "won" or (item.min is None and item.max is None):
        return True
    v = normalize(value, "won")
    if v is None or not v.isdigit():
        return True                                  # 실비·법령 준용 같은 글 값은 범위를 보지 않는다
    return (item.min is None or int(v) >= item.min) and (item.max is None or int(v) <= item.max)


def extract(llm, item: Item, inst: str, cands: list[Candidate]) -> Cell:
    """후보 조들에서 값과 인용을 뽑는다. 인용이 원문에 없거나 숫자가 인용과 다르면 한 번 더 묻고, 그래도 아니면 absent."""
    base = Cell(item.topic, item.id, inst, "absent")
    if not cands:
        base.note = "후보 없음"
        return base
    pattern = _pattern(len(cands))
    problem = None
    for _ in range(2):
        try:
            out = llm.regex(_prompt(item, cands, problem), pattern, max_tokens=300)
        except ProviderError as e:
            base.note = f"LLM 실패: {e}"
            return base
        m = re.fullmatch(pattern, out)
        if m is None or m[1] == "없음":
            base.note = "근거 없음"
            return base
        c = cands[int(m[1][1:]) - 1]
        value, quote = m[2].strip(), _clean(m[3])
        if item.norm != "boolean" and squash(value) in ("없음", "해당없음", "규정없음"):
            base.note = "근거 없음"
            return base
        got = resolve_quote(quote, value, c.text, table=c.article_path.startswith(("annex", "form")))
        if got is not None:
            quote, how = got
            if not in_bounds(value, item):
                problem = f"값 '{value}'은(는) 이 항목의 값으로 보기 어렵다(표의 다른 칸일 수 있다). 질문한 항목의 값을 찾을 것."
                continue
            if value_supported(value, item.norm, quote):
                u = locate(quote, c)
                rule_ok = normalize(value, item.norm) is not None
                conf = round((0.9 if item.norm in ("duration", "won") else 0.75) - PENALTY[how], 2)
                return Cell(item.topic, item.id, inst, "llm", c.work_id, c.version_id, u.pv_id if u else None,
                            u.path if u else c.article_path, value, normalize(value, item.norm), quote,
                            conf if rule_ok else 0.5, c.title)
            problem = f"값 '{value}'이(가) 인용 안에 없다. 인용 구절 안의 값을 그대로 쓸 것."
        else:
            problem = "인용이 조문 본문과 글자 그대로 일치하지 않는다. 조문에서 그대로 복사할 것."
    base.note = f"검증 실패: {problem} 마지막 답: {out!r}"
    return base
