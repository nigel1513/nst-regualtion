"""질의응답 흐름 (spec 8.2): 마스킹 → 기관 → 분석 → 검색 → 근거 확장 → 생성·검증 → 로그."""
import json
import time
from contextlib import nullcontext
from dataclasses import asdict

from reg.search.service import search
from reg.qa.analyze import analyze
from reg.qa.answer import generate
from reg.qa.evidence import expand
from reg.qa.institutions import load_aliases, resolve_mention
from reg.qa.mask import mask_pii

MIN_SCORE = 0.3


def _db(db):
    """연결 또는 연결 풀. 풀이면 DB 단계마다 잠깐 빌리고, LLM·검색을 기다리는 동안에는 돌려준다."""
    return nullcontext(db) if hasattr(db, "execute") else db.connection()


def _institutions(conn) -> list[dict]:
    return conn.execute("SELECT code, name FROM regulation.institution WHERE active ORDER BY id").fetchall()


def _log(conn, q: str, res: dict, user_inst, latency_ms: int, model: str | None, retrieved: list) -> int:
    ans = res.get("answer")
    row = conn.execute(
        "INSERT INTO ops.qa_log (question, institution, user_institution, as_of, status, verdict, release_id,"
        " model, retrieved, cited, verification, answer, latency_ms) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
        " RETURNING id",
        (q, res.get("institution"), user_inst, res.get("as_of"), res["status"], ans.get("결론") if ans else None,
         res.get("release_id"), model, json.dumps(retrieved, ensure_ascii=False),
         json.dumps([c["id"] for c in ans["근거"]] if ans else [], ensure_ascii=False),
         json.dumps(res.get("verification") or {}, ensure_ascii=False),
         json.dumps(ans, ensure_ascii=False) if ans else None, latency_ms)).fetchone()
    conn.commit()
    return row["id"]


def _with_lookup(found: dict) -> list[dict]:
    """질문이 번호 인용("여비규정 제27조 제1항…")이면 직접 조회한 조를 근거 1순위로 둔다 (M7 §2.2-1)."""
    hits = found["hits"]
    first = []
    for x in found.get("lookup") or []:
        if not any(h["version_id"] == x["version_id"] and h.get("article_path") == x["article_path"] for h in first):
            first.append({"work_id": x["work_id"], "version_id": x["version_id"], "path": x["path"],
                          "article_path": x["article_path"], "score": x["score"], "matches": [{"path": x["path"]}]})
    keys = {(h["version_id"], h["article_path"]) for h in first}
    return first[:1] + [h for h in hits if (h["version_id"], h.get("article_path")) not in keys]


def ask(db, deps: dict, question: str, institution: str | None = None, user_institution: str | None = None,
        as_of: str | None = None, log: bool = True) -> dict:
    """log=False: ops.qa_log에 쓰지 않는다 (읽기 전용 평가). 그때 id는 None."""
    t0 = time.monotonic()
    q = mask_pii(question.strip())
    with _db(db) as conn:
        aliases = load_aliases(conn)
    mention = resolve_mention(q, aliases)
    inst = institution or (mention if not (mention and user_institution and mention != user_institution)
                           else None) or (None if mention else user_institution)
    res = {"status": "", "institution": inst, "as_of": as_of, "question_type": None, "evidence": [], "answer": None,
           "verification": None, "verdict_source": None, "release_id": None, "note": None}

    def ms() -> int:
        return int((time.monotonic() - t0) * 1000)

    def record(conn, model, retrieved) -> int | None:
        res["retrieved"] = retrieved
        return _log(conn, q, res, user_institution, ms(), model, retrieved) if log else None

    if not inst:
        with _db(db) as conn:
            res.update(status="need_institution",
                       options=[{"code": i["code"], "name": i["name"]} for i in _institutions(conn)],
                       note="질문과 소속 기관이 달라 확인이 필요합니다" if mention and user_institution else
                       "어느 기관 규정 기준으로 볼까요? 기관마다 기한이 다릅니다.")
            res["id"] = record(conn, None, [])
        return res
    a = analyze(deps.get("llm"), q, aliases)
    res["question_type"] = a.question_type
    res["as_of"] = as_of = as_of or a.as_of
    query = " ".join([q, *a.terms])
    found = search(deps["os"], deps["embedder"], deps.get("reranker"), query, institution=inst, as_of=as_of,
                   rerank=True, size=10, aliases=aliases, facets=False, with_units=False)
    hits = _with_lookup(found)
    res["release_id"] = found["release_id"]
    retrieved = [{"version_id": h["version_id"], "path": h["path"], "score": h.get("rerank_score", h["score"])}
                 for h in hits]
    top = hits[0].get("rerank_score", 1.0) if hits else 0.0
    if not hits or (found["reranked"] and top < MIN_SCORE):
        with _db(db) as conn:
            res.update(status="not_found", note="관련 규정을 찾지 못했습니다. 아래는 가까운 후보입니다.",
                       evidence=[asdict(e) for e in expand(conn, hits[:5], limit_articles=5, as_of=as_of,
                                                           release_id=found["release_id"])])
            res["id"] = record(conn, None, retrieved)
        return res
    with _db(db) as conn:
        evidence = expand(conn, hits, as_of=as_of, release_id=found["release_id"])
        conn.commit()  # 풀에 돌려줄 때 열린 트랜잭션이 남지 않게
    res["evidence"] = [asdict(e) for e in evidence]
    gen = generate(deps["llm"], q, a, evidence) if deps.get("llm") else \
        {"answer": None, "verification": {"ok": False, "problems": ["llm_unavailable"]}, "verdict_source": None}
    res.update(answer=gen["answer"], verification=gen["verification"], verdict_source=gen.get("verdict_source"),
               status="answered" if gen["answer"] else "evidence_only")
    if not gen["answer"]:
        res["note"] = "자동 설명을 만들지 못해 근거 조문만 보여드립니다."
    with _db(db) as conn:
        res["id"] = record(conn, deps.get("llm_model"), retrieved)
    return res
