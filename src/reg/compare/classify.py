"""규정 ↔ 주제 분류 (spec §4): 제목 규칙이 먼저, 맞는 규칙이 없으면 목적 조항 규칙, 그다음 임베딩 유사도.
규정당 최대 2개.

제목 규칙: 주제마다 키워드를 두고, 긴 키워드부터 제목에서 찾아 자리를 차지한다(연수직이 연수보다 먼저). 한국어 복합
제목은 끝 쪽이 머리말이라("연구개발능률성과급지급지침"의 성과급) 끝에 가장 가까운 키워드의 주제가 첫째다.
임베딩: 제목 + 제1조(대개 목적 조항)를 bge-m3로 바꿔 주제 설명과의 코사인 유사도를 잰다. 제목이 깨진 규정
("<최종공포일 …>", "제정 1992-04-22")도 목적 조항으로 분류된다."""
import math
import re
from dataclasses import dataclass

MAX_TOPICS = 2
MIN_SIM = 0.45          # 이보다 낮으면 기타 (bge-m3, 2026-10-03 표본으로 정함)
SECOND_MARGIN = 0.015   # 둘째 주제는 첫째와 이만큼 가까울 때만
TITLE_SCORES = (1.0, 0.9)
EMBED_TEXT_MAX = 600
_STRIP = re.compile(r"[\s·ㆍ․・‧･]+")
_WORK_PREFIX = re.compile(r"^kr/reg/[^/]+/")          # 제목을 못 읽어 work id가 제목이 된 규정
# 목적 조항에서 근거 규정을 인용하는 부분("인사규정 제35조에 의거", "「공익신고자 보호법」에 따라")은 주제가 아니다
_CITED = re.compile(r"「[^」]*」|｢[^｣]*｣|[^\s,()]*(?:규정|규칙|요령|지침|기준|세칙|정관|법률|법|시행령|시행규칙)"
                    r"(?:\s*제\s*\d+\s*(?:조|장)(?:의\s*\d+)?(?:\s*제?\s*\d+\s*(?:항|호))*(?:\([^)]*\))?)?"
                    r"|\(이하[^)]*\)|[^\s(]*(?:연구원|연구소|연구회)")   # 기관 이름(안전성평가연구소의 '안전')도 뺀다
_PURPOSE = re.compile(r"제\s*1\s*조\s*\(\s*목\s*적\s*\)\s*(.{0,300}?)(?:목적|$)", re.S)
PURPOSE_SCORE = 0.8


@dataclass(frozen=True)
class WorkText:
    work_id: str
    title: str
    first_text: str = ""


def _norm(s: str) -> str:
    return _STRIP.sub("", s or "")


def purpose_text(first_text: str) -> str:
    """제1조(목적)에서 근거 인용을 뺀 본문. 목적 조항이 아니면 빈 글."""
    m = _PURPOSE.search(first_text or "")
    return _CITED.sub(" ", m[1]) if m else ""


def title_topics(title: str, topics) -> list[tuple[str, float]]:
    """제목 규칙. [(주제, 점수)] 최대 2개, 첫째가 제목의 머리말 주제."""
    t = _norm(_WORK_PREFIX.sub("", title or ""))
    owner: list[str | None] = [None] * len(t)    # 글자마다 자리를 차지한 주제. 같은 주제끼리는 겹쳐도 된다
    pairs = sorted(((_norm(k), tp.id) for tp in topics for k in tp.keywords if _norm(k)), key=lambda x: -len(x[0]))
    last: dict[str, int] = {}
    for kw, tid in pairs:
        start = 0
        while (at := t.find(kw, start)) >= 0:
            end = at + len(kw)
            if all(o in (None, tid) for o in owner[at:end]):
                owner[at:end] = [tid] * len(kw)
                last[tid] = max(last.get(tid, -1), end)
            start = at + 1
    ranked = sorted(last, key=lambda k: -last[k])[:MAX_TOPICS]
    return [(tid, TITLE_SCORES[i]) for i, tid in enumerate(ranked)]


def _cos(a: list[float], b: list[float]) -> float:
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0


def topic_text(t) -> str:
    return f"{t.label}: {t.description}"


def embed_text(w: WorkText) -> str:
    return f"{w.title}\n{w.first_text}"[:EMBED_TEXT_MAX]


def classify(works: list[WorkText], topics, embed, min_sim: float = MIN_SIM,
             margin: float = SECOND_MARGIN) -> dict[str, list[tuple[str, float, str]]]:
    """{work_id: [(주제, 점수, 방법)]}. 방법 = title | embedding | none(기타). embed(texts) -> 벡터 목록."""
    out: dict[str, list[tuple[str, float, str]]] = {}
    rest: list[WorkText] = []
    for w in works:
        got = title_topics(w.title, topics)
        if got:
            out[w.work_id] = [(t, s, "title") for t, s in got]
            continue
        got = title_topics(purpose_text(w.first_text), topics)   # 제목이 깨졌거나 낱말이 없으면 목적 조항
        if got:
            out[w.work_id] = [(t, round(PURPOSE_SCORE * s, 4), "purpose") for t, s in got[:1]]
        else:
            rest.append(w)
    cands = [t for t in topics if t.id != "other"]
    if rest:
        tv = embed([topic_text(t) for t in cands])
        wv = embed([embed_text(w) for w in rest])
        for w, v in zip(rest, wv):
            sims = sorted(((_cos(v, x), t.id) for t, x in zip(cands, tv)), reverse=True)
            (s1, t1), (s2, t2) = sims[0], sims[1]
            if s1 < min_sim:
                out[w.work_id] = [("other", 0.0, "none")]
                continue
            out[w.work_id] = [(t1, round(s1, 4), "embedding")] + \
                ([(t2, round(s2, 4), "embedding")] if s2 >= s1 - margin and s2 >= min_sim else [])
    return out
