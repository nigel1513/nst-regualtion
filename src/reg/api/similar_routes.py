"""규정 보기 오른쪽 레일 "다른 기관의 같은 조항" (서비스 UI 개편 §3): GET /api/v1/provision/similar?pv=&limit=

고른 조(조항 판본)의 임베딩으로 reg-provisions 별칭에서 knn을 돌려, 다른 기관의 현행 내부규정 조 중 의미가 가까운 것을 준다.
색인에 그 조의 벡터가 없으면(연혁 판본 등) 조 전문을 임베딩해서 찾는다. 기관마다 하나씩 먼저 고르고, 남으면 나머지로 채운다."""
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request

from reg.platform.llm import ProviderError

router = APIRouter()
CANDIDATES = 60
SNIPPET = 160
FIELDS = ["work_id", "version_id", "title", "institution", "institution_name", "article_path", "article_key",
          "label", "heading", "full_label", "text", "article_text", "unit", "window"]


def _href(work_id: str, article: str) -> str:
    return ("/regulations/" + "/".join(quote(s, safe="") for s in work_id.split("/"))
            + f"?a={quote(article, safe='')}#{quote(article, safe='')}")


def _snippet(doc: dict) -> str:
    body = doc.get("article_text") or doc.get("text") or ""
    lines = body.split("\n")
    if doc.get("article_text") and len(lines) > 1:
        lines = lines[1:]          # 첫 줄은 "제27조(출장증빙의 제출)" 머리말
    s = " ".join(x.strip() for x in lines if x.strip())
    return s[:SNIPPET] + ("…" if len(s) > SNIPPET else "")


def _source(c, pv: int) -> dict | None:
    return c.execute(
        "SELECT pv.id, pv.path, pv.unit, pv.number_label AS label, pv.heading, p.work_id, i.code AS institution,"
        " w.title FROM regulation.provision_version pv JOIN regulation.provision p ON p.id = pv.provision_id"
        " JOIN regulation.work w ON w.id = p.work_id LEFT JOIN regulation.institution i ON i.id = w.institution_id"
        " WHERE pv.id = %s", (pv,)).fetchone()


def _article_text(c, pv: int) -> str:
    """조와 그 아래 항·호를 한 덩어리로 (색인의 article_text와 같은 꼴)."""
    r = c.execute("SELECT path, number_label AS label, heading, text FROM regulation.provision_version WHERE id = %s",
                  (pv,)).fetchone()
    head = r["label"] + (f"({r['heading']})" if r["heading"] else "")
    kids = c.execute(
        "SELECT DISTINCT ON (pv.path) pv.path, pv.number_label AS label, pv.text, vp.ord"
        " FROM regulation.version_provision vp JOIN regulation.provision_version pv ON pv.id = vp.provision_version_id"
        " WHERE vp.work_version_id IN (SELECT work_version_id FROM regulation.version_provision"
        "   WHERE provision_version_id = %s) AND pv.path LIKE %s ORDER BY pv.path, vp.ord", (pv, r["path"] + ".%")).fetchall()
    kids.sort(key=lambda k: k["ord"])
    return "\n".join([head, r["text"] or "", *(f"{k['label']} {k['text']}" for k in kids)]).strip()


@router.get("/api/v1/provision/similar")
def similar(request: Request, pv: int, limit: int = Query(5, ge=1, le=20)):
    deps = request.app.state.search or {}
    os = deps.get("os")
    if not os or os.alias_target() is None:
        raise HTTPException(503, "검색 색인이 아직 없습니다")
    with request.app.state.pool.connection() as c:
        src = _source(c, pv)
        if not src:
            raise HTTPException(404, "조항을 찾을 수 없습니다")
        hit = os.search({"size": 1, "_source": ["embedding"], "sort": [{"window": "asc"}],
                         "query": {"bool": {"filter": [{"term": {"pv_id": pv}}]}}})["hits"]["hits"]
        vec = hit[0]["_source"].get("embedding") if hit else None
        text = None if vec else _article_text(c, pv)
    if not vec:
        embedder = deps.get("embedder")
        if embedder is None:
            raise HTTPException(503, "임베딩 서버가 없습니다")
        try:
            vec = embedder.embed([text])[0]
        except ProviderError as e:
            raise HTTPException(503, "임베딩 서버에 연결할 수 없습니다") from e
    flt: list[dict] = [{"term": {"version_state": "CURRENT"}}, {"term": {"family": "reg"}},
                       {"term": {"unit": "article"}}]
    must_not: list[dict] = [{"term": {"work_id": src["work_id"]}}]
    if src["institution"]:
        must_not.append({"term": {"institution": src["institution"]}})
    body = {"size": CANDIDATES, "_source": FIELDS,
            "query": {"knn": {"embedding": {"vector": vec, "k": CANDIDATES,
                                            "filter": {"bool": {"filter": flt, "must_not": must_not}}}}}}
    hits = os.search(body)["hits"]["hits"]
    seen: set[str] = set()
    uniq = []
    for h in hits:
        d = h["_source"]
        if d.get("article_key") in seen:
            continue
        seen.add(d.get("article_key"))
        uniq.append((h["_score"], d))
    first, rest, insts = [], [], set()
    for s, d in uniq:                       # 기관마다 가장 가까운 조 하나를 먼저
        (rest if d.get("institution") in insts else first).append((s, d))
        insts.add(d.get("institution"))
    picked = (first + rest)[:limit]
    items = [{"institution": d.get("institution"), "institution_name": d.get("institution_name"),
              "work_id": d["work_id"], "version_id": d.get("version_id"), "title": d.get("title"),
              "article_path": d.get("article_path"), "label": d.get("label"), "heading": d.get("heading"),
              "full_label": d.get("full_label"), "snippet": _snippet(d), "score": round(float(s), 4),
              "href": _href(d["work_id"], d.get("article_path") or "")} for s, d in picked]
    return {"source": {"pv_id": src["id"], "work_id": src["work_id"], "institution": src["institution"],
                       "label": src["label"], "title": src["title"]}, "items": items}
