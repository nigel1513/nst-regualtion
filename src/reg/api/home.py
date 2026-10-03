"""홈 화면 (서비스 UI 개편 §2): GET /api/v1/home?inst=

- 기관을 고르면: 기관 머리 수치, 최근 바뀐 규정(시행일 순)과 바뀐 조문 요약(provision_change), 주제별 규정 수(있으면).
- 기관이 없으면(전체): 기관별 현황 표(현행 규정, 판본, 최근 개정일, 열린 검수, 마지막 수집)."""
import re
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request

from reg.api.topics import has_topics, topic_label

router = APIRouter()

KIND_LABEL = {"ADDED": "신설", "DELETED": "삭제", "MODIFIED": "개정", "RENUMBERED": "조 이동"}
SKIP_UNITS = {"chapter", "section", "supplement", "supp_article"}
RE_NOTE = re.compile(r"\s*<[^>]*>?.*$")
RE_VALUE = re.compile(r"\d[\d,]*(?:\.\d+)?\s*(?:일|개월|년|시간|분|만원|천원|억원|원|%|퍼센트|명|회|세|km|킬로미터)")

STATS = """
SELECT i.code, i.name,
  (SELECT count(*) FROM regulation.work w WHERE w.institution_id = i.id AND w.status <> 'ABOLISHED'
     AND EXISTS (SELECT 1 FROM regulation.work_version v WHERE v.work_id = w.id AND v.version_state = 'CURRENT'))::int
     AS current_works,
  (SELECT count(*) FROM regulation.work_version v JOIN regulation.work w ON w.id = v.work_id
     WHERE w.institution_id = i.id)::int AS versions,
  (SELECT max(v.effective_from) FROM regulation.work_version v JOIN regulation.work w ON w.id = v.work_id
     WHERE w.institution_id = i.id AND v.effective_from <= current_date) AS last_amended,
  (SELECT max(sd.fetched_at) FROM regulation.work_version v JOIN regulation.work w ON w.id = v.work_id
     JOIN regulation.source_document sd ON sd.id = v.source_document_id WHERE w.institution_id = i.id) AS last_fetched,
  (SELECT count(*) FROM regulation.review_task t JOIN regulation.work w ON w.id = t.work_id
     WHERE w.institution_id = i.id AND t.status = 'OPEN')::int AS open_reviews
FROM regulation.institution i WHERE i.active AND (%(code)s::text IS NULL OR i.code = %(code)s) ORDER BY i.id
"""


def work_href(work_id: str, extra: str = "") -> str:
    return "/regulations/" + "/".join(quote(s, safe="") for s in work_id.split("/")) + extra


def _iso(v):
    return v.isoformat() if v is not None else None


def _stats(conn, code: str | None) -> list[dict]:
    rows = conn.execute(STATS, {"code": code}).fetchall()
    for r in rows:
        r["last_amended"], r["last_fetched"] = _iso(r["last_amended"]), _iso(r["last_fetched"])
    return rows


def _value_change(before: str | None, after: str | None) -> str | None:
    """기한·금액처럼 숫자 값 하나만 바뀌었으면 "3일 → 7일"."""
    if not before or not after:
        return None
    a, b = RE_VALUE.findall(before), RE_VALUE.findall(after)
    gone = [x for x in a if x not in b]
    new = [x for x in b if x not in a]
    if len(gone) == 1 and len(new) == 1:
        return f"{gone[0]} → {new[0]}"
    return None


def summarize_changes(rows: list[dict], limit: int = 3) -> dict:
    """바뀐 조항 행(kind, path, unit, from_text, to_text, label, heading, ord) → 조 단위 요약.

    label·heading은 소속 조의 라벨이다. 같은 조의 여러 항이 바뀌면 한 번만 쓴다. 조 전체가 생기거나 없어지면 신설·삭제."""
    arts: dict[str, dict] = {}
    for r in sorted(rows, key=lambda x: x.get("ord") if x.get("ord") is not None else 1e9):
        # 장·절 제목, 개정마다 붙는 부칙은 "바뀐 조문"이 아니다
        if r["kind"] == "ANNOTATION_ONLY" or r.get("unit") in SKIP_UNITS or r["path"].startswith("supp"):
            continue
        ap = r["path"].split(".")[0]
        own = ap == r["path"]
        heading = RE_NOTE.sub("", r.get("heading") or "").strip() or None   # "<개정 '19.1.21.>" 같은 주석은 뺀다
        a = arts.setdefault(ap, {"path": ap, "label": r["label"], "heading": heading, "kind": "MODIFIED",
                                 "detail": None, "values": []})
        if own and r["kind"] in ("ADDED", "DELETED", "RENUMBERED"):
            a["kind"] = r["kind"]
        if r["kind"] == "MODIFIED":
            v = _value_change(r.get("from_text"), r.get("to_text"))
            if v:
                a["values"].append(v)
    out = []
    for a in arts.values():
        a["detail"] = a["values"][0] if len(a["values"]) == 1 and a["kind"] == "MODIFIED" else None
        out.append({k: a[k] for k in ("path", "label", "heading", "kind", "detail")})
    shown = out[:limit]
    parts = []
    for a in shown:
        name = a["label"] + (f" {a['heading']}" if a["heading"] and a["detail"] else "")
        parts.append(f"{name} {a['detail']}" if a["detail"] else f"{a['label']} {KIND_LABEL.get(a['kind'], '개정')}")
    more = len(out) - len(shown)
    text = " · ".join(parts) + (f" 외 {more}건" if more else "")
    return {"articles": shown, "more": more, "text": text}


def _label(path: str, label: str) -> str:
    return "부칙" if path.startswith("supp") else label


def _recent(conn, code: str, limit: int) -> list[dict]:
    vers = conn.execute(
        "SELECT v.id, v.work_id, w.title, v.effective_from, v.amendment_kind,"
        " (SELECT count(*) FROM regulation.work_version x WHERE x.work_id = v.work_id)::int AS n_versions"
        " FROM regulation.work_version v JOIN regulation.work w ON w.id = v.work_id"
        " JOIN regulation.institution i ON i.id = w.institution_id"
        " WHERE i.code = %s AND v.version_state = 'CURRENT' AND w.status <> 'ABOLISHED'"
        " ORDER BY v.effective_from DESC NULLS LAST, w.title LIMIT %s", (code, limit)).fetchall()
    if not vers:
        return []
    ids = [v["id"] for v in vers]
    changes = conn.execute(
        "SELECT pc.to_version_id, pc.from_version_id, pc.kind, coalesce(t.path, f.path) AS path,"
        " coalesce(t.unit, f.unit) AS unit, f.text AS from_text, t.text AS to_text, vp.ord"
        " FROM regulation.provision_change pc"
        " LEFT JOIN regulation.provision_version t ON t.id = pc.to_pv_id"
        " LEFT JOIN regulation.provision_version f ON f.id = pc.from_pv_id"
        " LEFT JOIN regulation.version_provision vp ON vp.provision_version_id = pc.to_pv_id"
        "   AND vp.work_version_id = pc.to_version_id"
        " WHERE pc.to_version_id = ANY(%s) AND pc.kind <> 'ANNOTATION_ONLY'", (ids,)).fetchall()
    look = set(ids) | {c["from_version_id"] for c in changes if c["from_version_id"]}
    labels: dict[tuple[str, str], dict] = {}
    for r in conn.execute(
            "SELECT vp.work_version_id AS vid, pv.path, pv.number_label AS label, pv.heading, vp.ord"
            " FROM regulation.version_provision vp JOIN regulation.provision_version pv ON pv.id = vp.provision_version_id"
            " WHERE vp.work_version_id = ANY(%s) AND position('.' in pv.path) = 0", (list(look),)).fetchall():
        labels[(r["vid"], r["path"])] = r
    by_v: dict[str, list[dict]] = {}
    for c in changes:
        ap = c["path"].split(".")[0]
        lab = labels.get((c["to_version_id"], ap)) or labels.get((c["from_version_id"], ap)) or {}
        c["label"] = _label(ap, lab.get("label") or ap)
        c["heading"] = lab.get("heading")
        if c["ord"] is None:
            c["ord"] = lab.get("ord")
        by_v.setdefault(c["to_version_id"], []).append(c)
    out = []
    for v in vers:
        ak = v["amendment_kind"] or ""
        kind = "제정" if ("제정" in ak or (v["n_versions"] == 1 and not ak)) else ("전부개정" if "전부" in ak else "개정")
        out.append({"work_id": v["work_id"], "title": v["title"], "version_id": v["id"],
                    "effective_from": _iso(v["effective_from"]), "amendment_kind": v["amendment_kind"],
                    "kind_label": kind, "href": work_href(v["work_id"]),
                    "changes": summarize_changes(by_v.get(v["id"], []))})
    return out


def _topics(conn, code: str) -> list[dict] | None:
    if not has_topics(conn):
        return None
    try:
        rows = conn.execute(
            "SELECT wt.topic, count(DISTINCT wt.work_id)::int AS n FROM regulation.work_topic wt"
            " JOIN regulation.work w ON w.id = wt.work_id JOIN regulation.institution i ON i.id = w.institution_id"
            " WHERE i.code = %s AND w.status <> 'ABOLISHED' GROUP BY wt.topic ORDER BY n DESC, wt.topic",
            (code,)).fetchall()
    except Exception:
        conn.rollback()
        return None
    return [{"topic": r["topic"], "label": topic_label(r["topic"]), "count": r["n"]} for r in rows]


@router.get("/api/v1/home")
def home(request: Request, inst: str | None = Query(None, max_length=40), recent: int = Query(8, ge=1, le=30)):
    with request.app.state.pool.connection() as c:
        if inst:
            rows = _stats(c, inst)
            if not rows:
                raise HTTPException(404, "기관을 찾을 수 없습니다")
            return {"institution": rows[0], "recent": _recent(c, inst, recent), "topics": _topics(c, inst),
                    "institutions": None, "totals": None}
        rows = _stats(c, None)
    with_data = [r for r in rows if r["current_works"]]
    totals = {"institutions": len(with_data), "current_works": sum(r["current_works"] for r in rows),
              "versions": sum(r["versions"] for r in rows), "open_reviews": sum(r["open_reviews"] for r in rows),
              "last_fetched": max((r["last_fetched"] for r in rows if r["last_fetched"]), default=None)}
    return {"institution": None, "recent": [], "topics": None, "institutions": rows, "totals": totals}
