"""규정 찾기 (서비스 UI 개편 §3): GET /api/v1/regulations

규범문서는 수백~수천 건이라 한 번에 읽어 파이썬에서 거르고 센다(집계는 자기 축의 필터만 빼고 — 다른 값의 건수도 보이게).
종류는 제목 끝말로 나눈다: 규정(규정·규칙·정관·강령) / 요령·지침 / 기준·세칙 / 법령(law.go.kr 법령·행정규칙)."""
import threading
import time

from fastapi import APIRouter, Query, Request

from reg.api.home import work_href
from reg.api.topics import topic_label, work_topics

router = APIRouter()

KINDS = {"reg": "규정", "guide": "요령·지침", "standard": "기준·세칙", "law": "법령"}
STATUSES = {"current": "현행", "abolished": "폐지"}

ROWS = """
WITH cur AS (
  SELECT DISTINCT ON (v.work_id) v.work_id, v.id, v.effective_from, v.version_state
  FROM regulation.work_version v
  ORDER BY v.work_id, (v.version_state = 'CURRENT') DESC, v.effective_from DESC NULLS LAST, v.created_at DESC)
SELECT w.id, w.title, w.status, w.abolished_on, i.code AS institution, i.name AS institution_name, i.id AS inst_ord,
  cur.id AS version_id, cur.effective_from, cur.version_state,
  (SELECT count(*) FROM regulation.version_provision vp JOIN regulation.provision_version pv
     ON pv.id = vp.provision_version_id WHERE vp.work_version_id = cur.id AND pv.unit = 'article')::int AS articles
FROM regulation.work w LEFT JOIN regulation.institution i ON i.id = w.institution_id
LEFT JOIN cur ON cur.work_id = w.id
"""


_LOCK = threading.Lock()
CACHE_SECONDS = 60      # 목록 기본 행은 수집·처리 때만 바뀐다: 앱마다 잠깐 기억해 두면 거르기·페이지 이동이 즉시


def _base_rows(request: Request) -> tuple[list[dict], dict[str, list[str]] | None, dict[str, str]]:
    st = request.app.state
    with _LOCK:
        hit = getattr(st, "reg_rows", None)
        if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
            return hit[1]
        with st.pool.connection() as c:
            rows = c.execute(ROWS).fetchall()
            topics = work_topics(c)
            names = {r["code"]: r["name"] for r in c.execute(
                "SELECT code, name FROM regulation.institution WHERE active ORDER BY id").fetchall()}
        for r in rows:
            r["kind"] = kind_group(r["id"], r["title"])
            r["st"] = _status(r)
            r["topic_keys"] = (topics or {}).get(r["id"], [])
        st.reg_rows = (time.monotonic(), (rows, topics, names))
        return rows, topics, names


def kind_group(work_id: str, title: str) -> str:
    if work_id.startswith(("kr/law/", "kr/admrul/")):
        return "law"
    t = (title or "").rstrip()
    if t.endswith(("요령", "지침")):
        return "guide"
    if t.endswith(("기준", "세칙")):
        return "standard"
    return "reg"


def _status(r: dict) -> str:
    return "abolished" if r["status"] == "ABOLISHED" else "current"


def _terms(q: str | None) -> list[str]:
    return [t for t in (q or "").lower().split() if t]


def _matches(r: dict, terms: list[str]) -> bool:
    hay = f"{r['title']} {r['institution_name'] or ''}".lower()
    return all(t in hay for t in terms)


def _relevance(r: dict, q: str) -> tuple:
    t = r["title"].lower()
    q = q.lower().strip()
    return (t != q, not t.startswith(q), q not in t, len(t), t)


@router.get("/api/v1/regulations")
def regulations(request: Request, q: str | None = Query(None, max_length=100),
                inst: list[str] | None = Query(None),
                topic: list[str] | None = Query(None),
                kind: list[str] | None = Query(None),
                status: str = Query("current", pattern="^(current|abolished|all)$"),
                sort: str | None = Query(None, pattern="^(relevance|title|recent|articles|institution)$"),
                page: int = Query(1, ge=1, le=10_000), size: int = Query(50, ge=1, le=500)):
    rows, topics, names = _base_rows(request)
    terms = _terms(q)
    insts, kinds, tps = set(inst or []), set(kind or []), set(topic or [])

    def keep(r: dict, skip: str | None = None) -> bool:
        if terms and not _matches(r, terms):
            return False
        if skip != "inst" and insts and (r["institution"] or "") not in insts:
            return False
        if skip != "kind" and kinds and r["kind"] not in kinds:
            return False
        if skip != "topic" and tps and not tps & set(r["topic_keys"]):
            return False
        return skip == "status" or status == "all" or r["st"] == status

    def count(axis: str, key) -> dict:
        out: dict = {}
        for r in rows:
            if keep(r, axis):
                for k in key(r):
                    out[k] = out.get(k, 0) + 1
        return out

    by_inst = count("inst", lambda r: [r["institution"]] if r["institution"] else [])
    by_kind = count("kind", lambda r: [r["kind"]])
    by_status = count("status", lambda r: [r["st"]])
    by_topic = count("topic", lambda r: r["topic_keys"]) if topics is not None else {}
    present = {r["institution"] for r in rows if r["institution"]}
    facets = {
        "institution": [{"value": code, "name": name, "count": by_inst.get(code, 0)}
                        for code, name in names.items() if code in present],
        "kind": [{"value": k, "label": lab, "count": by_kind.get(k, 0)} for k, lab in KINDS.items()],
        "status": [{"value": k, "label": lab, "count": by_status.get(k, 0)} for k, lab in STATUSES.items()],
        "topic": sorted(({"value": k, "label": topic_label(k), "count": n} for k, n in by_topic.items()),
                        key=lambda x: (-x["count"], x["label"])),
    }
    hits = [r for r in rows if keep(r)]
    mode = sort or ("relevance" if terms else "institution")
    if mode == "relevance" and terms:
        hits.sort(key=lambda r: _relevance(r, q or ""))
    elif mode == "recent":
        hits.sort(key=lambda r: (r["effective_from"] is None, -(r["effective_from"].toordinal() if r["effective_from"] else 0), r["title"]))
    elif mode == "articles":
        hits.sort(key=lambda r: (-r["articles"], r["title"]))
    elif mode == "title":
        hits.sort(key=lambda r: r["title"])
    else:
        hits.sort(key=lambda r: (r["inst_ord"] is None, r["inst_ord"] or 0, r["title"]))
    start = (page - 1) * size
    items = [{"id": r["id"], "title": r["title"], "institution": r["institution"],
              "institution_name": r["institution_name"], "kind": r["kind"], "kind_label": KINDS[r["kind"]],
              "topics": [{"topic": t, "label": topic_label(t)} for t in r["topic_keys"]],
              "effective_from": r["effective_from"].isoformat() if r["effective_from"] else None,
              "version_state": r["version_state"], "articles": r["articles"], "status": r["status"],
              "abolished_on": r["abolished_on"].isoformat() if r["abolished_on"] else None,
              "href": work_href(r["id"])} for r in hits[start:start + size]]
    return {"total": len(hits), "page": page, "size": size, "sort": mode, "items": items, "facets": facets,
            "topics_available": topics is not None}
