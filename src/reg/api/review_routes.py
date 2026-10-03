"""검수 작업 API (서비스 UI 스펙 §6). app.py에는 include_router 한 줄만 더한다.

GET  /api/v1/review-tasks              목록(필터·페이지·집계)
GET  /api/v1/review-tasks/{id}         한 건
POST /api/v1/review-tasks/{id}/assign|resolve|dismiss|hold|reopen
POST /api/v1/review-tasks/bulk-assign
"""
from typing import Literal
from urllib.parse import quote, urlencode

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from reg.core import review as R

router = APIRouter()

Status = Literal["OPEN", "HOLD", "RESOLVED", "DISMISSED"]
Name = Field(None, max_length=50)


def _strip(v):
    return (v.strip() or None) if isinstance(v, str) else v


class AssignIn(BaseModel):
    assignee: str | None = Name
    _s = field_validator("assignee")(_strip)


class ResolveIn(BaseModel):
    decision: dict = Field(default_factory=dict)
    note: str | None = Field(None, max_length=1000)
    by: str | None = Name


class DismissIn(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)
    by: str | None = Name

    @field_validator("reason")
    @classmethod
    def _nonblank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("사유가 필요합니다")
        return v.strip()


class NoteIn(BaseModel):
    note: str | None = Field(None, max_length=1000)
    by: str | None = Name


class BulkAssignIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)
    assignee: str | None = Name
    _s = field_validator("assignee")(_strip)


# 작업 → 규범문서·기관·ALIO 원장. 원본 단위 LOW_TEXT(source:{id})는 work_id가 없어 ALIO 파일·seq로 찾는다.
BASE = f"""
SELECT t.id, t.kind, t.target, t.work_id, t.detail, t.status, t.assignee, t.decision, t.created_at, t.resolved_at,
  w.id AS wid, coalesce(w.title, ar.title) AS work_title, i.code AS inst_code, i.name AS inst_name,
  ar.detail->>'jidtDptm' AS dept_code, {R.LAW_PENDING_SQL} AS law_pending
FROM regulation.review_task t
LEFT JOIN LATERAL (SELECT f.seq FROM regulation.alio_rule_file f WHERE t.work_id IS NULL AND t.target LIKE 'source:%%'
  AND f.source_document_id = CASE WHEN t.target ~ '^source:[0-9]+$' THEN substr(t.target, 8)::bigint END LIMIT 1) sf
  ON true
LEFT JOIN LATERAL (SELECT w2.id FROM regulation.work w2 WHERE t.work_id IS NULL AND w2.external_ids ? 'alio_seq'
  AND w2.external_ids->>'alio_seq' = coalesce(t.detail->>'seq', sf.seq)) ws ON true
LEFT JOIN regulation.work w ON w.id = coalesce(t.work_id, ws.id)
LEFT JOIN regulation.alio_rule ar ON ar.seq = coalesce(w.external_ids->>'alio_seq', t.detail->>'seq', sf.seq)
LEFT JOIN regulation.institution i ON i.id = coalesce(w.institution_id, ar.institution_id)
"""


def _where(status, inst, kind, assignee, q, group, ids=None) -> tuple[str, dict]:
    cond, p = [], {}
    if ids is not None:
        cond.append("t.id = ANY(%(ids)s)")
        p["ids"] = ids
    if status:
        cond.append("t.status = ANY(%(status)s)")
        p["status"] = status
    if inst:
        cond.append("i.code = ANY(%(inst)s)")
        p["inst"] = inst
    if kind:
        cond.append("t.kind = ANY(%(kind)s)")
        p["kind"] = kind
    if assignee == "none":
        cond.append("t.assignee IS NULL")
    elif assignee:
        cond.append("t.assignee = %(assignee)s")
        p["assignee"] = assignee
    if q:
        cond.append("(coalesce(w.title, ar.title) ILIKE %(q)s ESCAPE '\\' OR t.detail::text ILIKE %(q)s ESCAPE '\\')")
        p["q"] = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    if group == "law_pending":
        cond.append(R.LAW_PENDING_SQL)
    elif group == "default":
        cond.append("NOT " + R.LAW_PENDING_SQL)
    return (" WHERE " + " AND ".join(cond)) if cond else "", p


def _versions(conn, rows: list[dict]) -> dict[int, dict]:
    """작업의 판본: 버전 대상이면 그 버전, 아니면 규범문서의 현행(없으면 가장 늦은) 버전."""
    by_target = [r["target"] for r in rows if r["kind"] in R.VERSION_KINDS or r["target"].startswith("kr/")]
    wids = list({r["wid"] for r in rows if r["wid"]})
    vs = conn.execute(
        "SELECT v.id, v.work_id, v.effective_from, v.version_state, sd.view_blob_key IS NOT NULL AS has_view"
        " FROM regulation.work_version v JOIN regulation.source_document sd ON sd.id = v.source_document_id"
        " WHERE v.id = ANY(%s)", (by_target,)).fetchall() if by_target else []
    exact = {v["id"]: v for v in vs}
    cur = {v["work_id"]: v for v in conn.execute(
        "SELECT DISTINCT ON (v.work_id) v.id, v.work_id, v.effective_from, v.version_state,"
        " sd.view_blob_key IS NOT NULL AS has_view FROM regulation.work_version v"
        " JOIN regulation.source_document sd ON sd.id = v.source_document_id WHERE v.work_id = ANY(%s)"
        " ORDER BY v.work_id, (v.version_state = 'CURRENT') DESC, v.effective_from DESC NULLS LAST, v.created_at DESC",
        (wids,)).fetchall()} if wids else {}
    return {r["id"]: exact.get(r["target"]) or cur.get(r["wid"]) for r in rows}


def _span(r: dict) -> int | None:
    """ref:{work}:{path}:{span}:{name} 에서 span (work·path에 ':'가 있어도 앞에서 잘라 낸다)."""
    pre = f"ref:{r['work_id']}:{r['detail'].get('path')}:"
    if r["target"].startswith(pre):
        s = r["target"][len(pre):].split(":", 1)[0]
        return int(s) if s.isdigit() else None
    return None


def _texts(conn, rows: list[dict], ver: dict[int, dict]) -> tuple[dict, dict]:
    """(버전, 경로) → 조항 글, 버전 → 시행일 부칙 글. 한 페이지 분만 읽는다."""
    pairs = [(ver[r["id"]]["id"], r["detail"].get("path")) for r in rows
             if r["kind"] in R.REF_KINDS and ver[r["id"]] and r["detail"].get("path")]
    prov = {}
    if pairs:
        for x in conn.execute(
                "SELECT x.v, x.p, pv.text FROM unnest(%s::text[], %s::text[]) AS x(v, p)"
                " JOIN regulation.version_provision vp ON vp.work_version_id = x.v"
                " JOIN regulation.provision_version pv ON pv.id = vp.provision_version_id AND pv.path = x.p",
                ([a for a, _ in pairs], [b for _, b in pairs])).fetchall():
            prov[(x["v"], x["p"])] = x["text"]
    dated = list({ver[r["id"]]["id"] for r in rows if r["kind"] in ("EFFECTIVE_DATE", "CONFLICT") and ver[r["id"]]})
    supp = {x["v"]: x for x in conn.execute(
        "SELECT DISTINCT ON (vp.work_version_id) vp.work_version_id AS v, pv.path, pv.text"
        " FROM regulation.version_provision vp JOIN regulation.provision_version pv ON pv.id = vp.provision_version_id"
        " WHERE vp.work_version_id = ANY(%s) AND pv.path LIKE 'supp%%' AND pv.text LIKE '%%시행%%'"
        " ORDER BY vp.work_version_id, vp.ord DESC", (dated,)).fetchall()} if dated else {}
    return prov, supp


def _seg(s: str) -> str:
    return "/".join(quote(p, safe="") for p in s.split("/"))


def _links(wid: str | None, v: dict | None, path: str | None) -> dict:
    out = {"viewer": None, "source": None, "pdf": None, "original": None}
    if not wid:
        return out
    q = {}
    if v and v["version_state"] != "CURRENT" and v["effective_from"]:
        q["as_of"] = v["effective_from"].isoformat()
    if art := R.article_of(path):
        q["a"] = art
    out["viewer"] = f"/regulations/{_seg(wid)}" + (f"?{urlencode(q)}" if q else "") + \
        (f"#{quote(path, safe='@/~-.')}" if path else "")
    if v:
        sq = {"version": v["id"], **({"a": art} if art else {})}
        out["source"] = f"/source/{_seg(wid)}?{urlencode(sq)}"
        base = f"/api/v1/file?{urlencode({'version': v['id']})}"
        out["pdf"] = f"{base}&kind=view" if v["has_view"] else None
        out["original"] = f"{base}&kind=original"
    return out


def _enrich(conn, rows: list[dict]) -> list[dict]:
    if not rows:
        return []
    ver = _versions(conn, rows)
    prov, supp = _texts(conn, rows, ver)
    out = []
    for r in rows:
        d, v, k = r["detail"] or {}, ver[r["id"]], r["kind"]
        path, ex = None, None
        if k in R.REF_KINDS:
            path = d.get("path")
            text = prov.get((v["id"], path)) if v else None
            if text is not None:
                ex = R.excerpt(text, _span(r), d.get("evidence"))
        elif k in ("EFFECTIVE_DATE", "CONFLICT") and v and v["id"] in supp:
            path = supp[v["id"]]["path"]
            ex = R.date_excerpt(supp[v["id"]]["text"])
        label = R.path_label(path)
        if k == "PARSE":
            miss = [f"a{n}" for n in d.get("missing") or []]
            label = R.path_labels(miss or d.get("diff") or []) or "전체"
            path = None if miss else (d.get("diff") or [None])[0]  # 빠진 조는 문서에 없어 앵커가 없다
        out.append({
            "id": r["id"], "kind": k, "kind_label": R.KIND_LABEL.get(k, k), "target": r["target"],
            "work_id": r["work_id"], "work_title": r["work_title"], "detail": d, "status": r["status"],
            "created_at": r["created_at"], "resolved_at": r["resolved_at"],
            "institution": {"code": r["inst_code"], "name": r["inst_name"]} if r["inst_code"] else None,
            "work": {"id": r["wid"], "title": r["work_title"]} if r["wid"] else None,
            "version": {"id": v["id"], "effective_from": v["effective_from"], "state": v["version_state"]} if v else None,
            "location": {"label": label, "path": path},
            "excerpt": ex,
            "problem": R.problem(k, d), "todo": R.todo(k, d), "law_pending": r["law_pending"],
            "department": R.department(r["dept_code"]),
            "assignee": r["assignee"], "decision": r["decision"],
            "links": _links(r["wid"], v, path),
        })
    return out


def _summary(conn) -> dict:
    """열린·보류 작업 전체 집계(필터와 무관). open·unassigned·by_*는 법령 적재 대기를 뺀 열린 작업."""
    rows = conn.execute("SELECT kind, inst_code AS inst, status, assignee IS NULL AS unassigned, law_pending AS lp,"
                        " count(*)::int AS n FROM (" + BASE + " WHERE t.status = ANY(%(s)s)) b GROUP BY 1, 2, 3, 4, 5",
                        {"s": list(R.ACTIVE)}).fetchall()
    s = {"open": 0, "hold": 0, "unassigned": 0, "law_pending": 0, "by_kind": {}, "by_institution": {}}
    for r in rows:
        if r["status"] == "HOLD":
            s["hold"] += r["n"]
            continue
        if r["lp"]:
            s["law_pending"] += r["n"]
            continue
        s["open"] += r["n"]
        s["unassigned"] += r["n"] if r["unassigned"] else 0
        s["by_kind"][r["kind"]] = s["by_kind"].get(r["kind"], 0) + r["n"]
        key = r["inst"] or "law"
        s["by_institution"][key] = s["by_institution"].get(key, 0) + r["n"]
    return s


def list_tasks(conn, status=("OPEN",), inst=None, kind=None, assignee=None, q=None, group="default", page=1,
               size=50, summary=True) -> dict:
    where, p = _where(list(status) if status else None, inst, kind, assignee, q, group)
    p.update(limit=size, offset=(page - 1) * size)
    rows = conn.execute("SELECT *, count(*) OVER () AS total FROM (" + BASE + where + ") x"
                        " ORDER BY created_at DESC, id DESC LIMIT %(limit)s OFFSET %(offset)s", p).fetchall()
    total = rows[0]["total"] if rows else conn.execute(
        "SELECT count(*)::int AS n FROM (" + BASE + where + ") x", p).fetchone()["n"]
    return {"items": _enrich(conn, rows), "total": total, "page": page, "size": size,
            "summary": _summary(conn) if summary else None}


def get_task(conn, task_id: int) -> dict | None:
    where, p = _where(None, None, None, None, None, "all", ids=[task_id])
    rows = conn.execute(BASE + where, p).fetchall()
    return _enrich(conn, rows)[0] if rows else None


def _pool(request: Request):
    return request.app.state.pool.connection()


@router.get("/api/v1/review-tasks")
def review_tasks(request: Request,
                 status: list[Status] = Query(["OPEN"]),
                 inst: list[str] | None = Query(None), kind: list[str] | None = Query(None),
                 assignee: str | None = Query(None, max_length=50), q: str | None = Query(None, max_length=100),
                 group: Literal["default", "law_pending", "all"] = "default",
                 page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=100), summary: bool = True):
    with _pool(request) as c:
        return list_tasks(c, status, inst, kind, (assignee or "").strip() or None, (q or "").strip() or None,
                          group, page, size, summary)


@router.get("/api/v1/review-tasks/{task_id}")
def review_task(request: Request, task_id: int):
    with _pool(request) as c:
        t = get_task(c, task_id)
    if t is None:
        raise HTTPException(404, "검수 작업을 찾을 수 없습니다")
    return t


def _act(request: Request, task_id: int, fn, *args):
    with _pool(request) as c:
        try:
            fn(c, task_id, *args)
        except R.ReviewError as e:
            c.rollback()
            raise HTTPException(e.code, str(e)) from None
        c.commit()
        return get_task(c, task_id)


@router.post("/api/v1/review-tasks/bulk-assign")
def bulk_assign(request: Request, body: BulkAssignIn):
    with _pool(request) as c:
        out = R.bulk_assign(c, body.ids, body.assignee)
        c.commit()
    return out


@router.post("/api/v1/review-tasks/{task_id}/assign")
def assign(request: Request, task_id: int, body: AssignIn):
    return _act(request, task_id, R.assign, body.assignee)


@router.post("/api/v1/review-tasks/{task_id}/resolve")
def resolve(request: Request, task_id: int, body: ResolveIn):
    return _act(request, task_id, _resolve, body)


@router.post("/api/v1/review-tasks/{task_id}/dismiss")
def dismiss(request: Request, task_id: int, body: DismissIn):
    return _act(request, task_id, _dismiss, body)


@router.post("/api/v1/review-tasks/{task_id}/hold")
def hold(request: Request, task_id: int, body: NoteIn | None = None):
    body = body or NoteIn()
    return _act(request, task_id, R.hold, body.note, body.by)


@router.post("/api/v1/review-tasks/{task_id}/reopen")
def reopen(request: Request, task_id: int, body: NoteIn | None = None):
    body = body or NoteIn()
    return _act(request, task_id, R.reopen, body.note, body.by)


def _abolish(c, task_id: int, confirm: bool) -> None:
    """폐지 후보는 ALIO 원장(alio_rule)이 진실이다: reconcile.decide로 원장까지 바꾼다(커밋한다)."""
    from reg.sources.alio.reconcile import AbolishError, decide

    t = c.execute("SELECT kind, work_id, status FROM regulation.review_task WHERE id = %s", (task_id,)).fetchone()
    if t is None:
        raise R.ReviewError(404, "검수 작업을 찾을 수 없습니다")
    if t["status"] not in R.ACTIVE:
        raise R.ReviewError(409, f"이미 닫힌 작업입니다 (현재 {t['status']})")
    try:
        decide(c, t["work_id"], confirm)
    except AbolishError as e:
        raise R.ReviewError(409, str(e)) from None


def _is_abolished(c, task_id: int) -> bool:
    r = c.execute("SELECT kind FROM regulation.review_task WHERE id = %s", (task_id,)).fetchone()
    return bool(r and r["kind"] == "ABOLISHED")


def _resolve(c, task_id: int, body: ResolveIn) -> None:
    if _is_abolished(c, task_id):
        _abolish(c, task_id, True)
        _relabel(c, task_id, R.record_decision("resolve", body.by, value={"confirm": True, **body.decision}, note=body.note))
        return
    R.resolve(c, task_id, body.decision, body.note, body.by)


def _dismiss(c, task_id: int, body: DismissIn) -> None:
    if _is_abolished(c, task_id):
        _abolish(c, task_id, False)
        _relabel(c, task_id, R.record_decision("dismiss", body.by, value={"confirm": False}, reason=body.reason))
        return
    R.dismiss(c, task_id, body.reason, body.by)


def _relabel(c, task_id: int, decision: dict) -> None:
    """decide()가 닫은 폐지 작업에 사람 기록(누가·언제·메모)을 덧붙인다."""
    import json

    c.execute("UPDATE regulation.review_task SET decision = %s WHERE id = %s",
              (json.dumps(decision, ensure_ascii=False), task_id))
