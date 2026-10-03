"""읽기 전용 규정 API (spec 10, NFR-02: LLM 없이 열람·검색)."""
import threading
from contextlib import asynccontextmanager
from datetime import date
from typing import Literal
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import Response
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, Field

from reg.api import queries as Q
from reg.api.annex_routes import router as annex_router
from reg.api.compare_routes import router as compare_router
from reg.platform.storage.blob import BlobStore

QA_SLOTS = 3  # 동시에 생성하는 답변 수 (vLLM 한 대, DB 풀 8개 중 일부만 쓴다)


class QaIn(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    institution: str | None = None
    user_institution: str | None = None
    as_of: date | None = None


class AlertStatusIn(BaseModel):
    status: Literal["ACKED", "ACTION_REQUIRED", "NO_ACTION", "RESOLVED"]
    note: str | None = Field(None, max_length=1000)


class FeedbackIn(BaseModel):
    feedback: Literal["helpful", "not_helpful"]
    reason: str | None = Field(None, max_length=300)


def create_app(dsn: str, blob: BlobStore, search_deps: dict | None = None) -> FastAPI:
    pool = ConnectionPool(dsn, min_size=1, max_size=8, kwargs={"row_factory": dict_row}, open=False)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        pool.open()
        yield
        pool.close()

    app = FastAPI(title="NST 규정·법령 API", version="0.3", lifespan=lifespan)
    app.state.pool = pool
    app.state.qa_slots = threading.BoundedSemaphore(QA_SLOTS)
    app.state.blob = blob
    app.state.search = search_deps or {}
    app.include_router(annex_router)

    def conn(request: Request):
        with request.app.state.pool.connection() as c:
            yield c

    @app.get("/api/v1/institutions")
    def institutions(c=Depends(conn)):
        return Q.institutions(c)

    @app.get("/api/v1/works")
    def works(institution: str | None = None, kind: str | None = Query(None, pattern="^(law|reg)$"),
              q: str | None = None, c=Depends(conn)):
        return Q.works(c, institution, kind, q)

    def _work_or_404(c, work_id: str) -> dict:
        w = Q.work(c, work_id)
        if not w:
            raise HTTPException(404, "규정을 찾을 수 없습니다")
        return w

    @app.get("/api/v1/work/versions")
    def versions(id: str, c=Depends(conn)):
        _work_or_404(c, id)
        return Q.versions(c, id)

    @app.get("/api/v1/work/view")
    def view(id: str, as_of: date | None = None, version: str | None = None, c=Depends(conn)):
        w = _work_or_404(c, id)
        v = Q.version_by_id(c, version) if version else Q.pick_version(c, id, as_of)
        if v and v["work_id"] != id:
            v = None
        if not v:
            raise HTTPException(404, "그 날짜에 시행 중인 버전이 없습니다" if as_of else "버전이 없습니다")
        sd = Q.source(c, v.pop("source_document_id"))
        v["source"] = {"source": sd["source"], "url": sd["url"], "mime": sd["mime"], "view_status": sd["view_status"],
                       "file_name": (sd["source_meta"] or {}).get("file_name"), "has_view": bool(sd["view_blob_key"])}
        provs = Q.provisions(c, v["id"])
        return {"work": w, "version": v, "provisions": provs, "refs": Q.refs_for(c, [p["id"] for p in provs]),
                "history": Q.history(c, v["id"]), "tasks": Q.open_tasks(c, v["id"])}

    @app.get("/api/v1/file")
    def file(version: str, kind: str = Query("view", pattern="^(view|original)$"), c=Depends(conn)):
        v = Q.version_by_id(c, version)
        if not v:
            raise HTTPException(404, "버전을 찾을 수 없습니다")
        sd = Q.source(c, v["source_document_id"])
        if kind == "view":
            if not sd["view_blob_key"]:
                raise HTTPException(404, "보기용 PDF가 없습니다")
            return Response(app.state.blob.get(sd["view_blob_key"]), media_type="application/pdf",
                            headers={"Cache-Control": "private, max-age=3600"})
        name = (sd["source_meta"] or {}).get("file_name") or f"{v['title']}.{sd['blob_key'].rsplit('.', 1)[-1]}"
        return Response(app.state.blob.get(sd["blob_key"]), media_type=sd["mime"],
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})

    @app.get("/api/v1/references")
    def references(pv: list[int] = Query(...), c=Depends(conn)):
        return Q.references(c, pv)

    @app.get("/api/v1/diff")
    def diff(from_: str = Query(..., alias="from"), to: str = Query(...), c=Depends(conn)):
        a, b = Q.version_by_id(c, from_), Q.version_by_id(c, to)
        if not a or not b:
            raise HTTPException(404, "버전을 찾을 수 없습니다")
        if a["work_id"] != b["work_id"]:
            raise HTTPException(400, "같은 규정의 버전끼리만 비교할 수 있습니다")
        for v in (a, b):
            v.pop("source_document_id")
        return {"from": a, "to": b, "changes": Q.diff(c, from_, to)}

    @app.get("/api/v1/search")
    def search(q: str = Query(..., min_length=2), institution: str | None = None, c=Depends(conn)):
        return Q.search(c, q, institution)

    @app.get("/api/v1/review-tasks")
    def review_tasks(status: str = Query("OPEN", pattern="^(OPEN|RESOLVED|DISMISSED)$"), kind: str | None = None,
                     c=Depends(conn)):
        return Q.review_tasks(c, status, kind)

    def _search_deps() -> dict:
        deps = app.state.search
        if not deps or deps["os"].alias_target() is None:
            raise HTTPException(503, "검색 색인이 아직 없습니다")
        return deps

    def _aliases(c) -> dict[str, list[str]]:
        rows = c.execute("SELECT code, name, aliases FROM regulation.institution WHERE active").fetchall()
        return {r["code"]: list(dict.fromkeys([r["name"], *(r["aliases"] or []), r["code"]])) for r in rows}

    @app.get("/api/v1/hsearch")
    def hsearch(q: str = Query(..., min_length=2, max_length=300), institution: str | None = None,
                as_of: date | None = None, kind: str | None = Query(None, pattern="^(law|reg|admrul)$"),
                unit: list[str] | None = Query(None), current_only: bool = True, rerank: bool = True,
                size: int = Query(10, ge=1, le=50), facets: bool = True, c=Depends(conn)):
        """조 단위로 묶은 하이브리드 검색 (M7 §2.2). 옛 필드(chunk_id·path·path_label·text·score) + matches·units·
        facets·lookup(번호 인용이면 직접 조회 결과)."""
        from reg.search.service import search as provision_search

        deps = _search_deps()
        aliases = _aliases(c)
        c.rollback()          # 검색을 기다리는 동안 트랜잭션을 열어 두지 않는다
        return provision_search(deps["os"], deps["embedder"], deps.get("reranker"), q, institution=institution,
                                as_of=as_of.isoformat() if as_of else None, kind=kind, unit=unit,
                                current_only=current_only, rerank=rerank, size=size, aliases=aliases, facets=facets)

    @app.get("/api/v1/search/lookup")
    def search_lookup(q: str = Query(..., min_length=2, max_length=200), as_of: date | None = None,
                      size: int = Query(5, ge=1, le=20), c=Depends(conn)):
        """조문 번호 직접 조회: "천문연 여비규정 27조 1항" → 그 항 (M7 §2.2-1)."""
        from reg.search.lookup import lookup

        deps = _search_deps()
        aliases = _aliases(c)
        c.rollback()
        return lookup(deps["os"], q, aliases, as_of=as_of.isoformat() if as_of else None, size=size)

    @app.get("/api/v1/search/suggest")
    def search_suggest(q: str = Query(..., min_length=1, max_length=100), institution: str | None = None,
                       size: int = Query(8, ge=1, le=20)):
        """규정명 자동완성 (M7 §2.2-5)."""
        from reg.search.suggest import suggest

        return suggest(_search_deps()["os"], q, institution, size)

    def _graph_related(request: Request):
        """QA 근거 확장용 구조 그래프 (M7-Q). 드라이버를 못 만들면 None — QA는 PostgreSQL 방식으로 간다."""
        from reg.api.graph_routes import _driver
        from reg.graph.query import expand as graph_expand

        def related(pv_ids, as_of):
            return graph_expand(_driver(request), pv_ids, as_of, depth=1)

        return related

    @app.post("/api/v1/qa")
    def qa(body: QaIn, request: Request):
        from reg.qa.service import ask

        deps = app.state.search
        if deps and "related" not in deps:
            deps = {**deps, "related": _graph_related(request)}
        if not deps or deps["os"].alias_target() is None:
            raise HTTPException(503, "검색 색인이 아직 없습니다")
        # 답변 생성은 GPU 한 대를 나눠 쓴다: 동시에 QA_SLOTS개까지만 받고, DB 연결은 단계마다 잠깐씩만 빌린다
        if not app.state.qa_slots.acquire(blocking=False):
            raise HTTPException(429, "질의가 몰려 있습니다. 잠시 후 다시 시도해 주세요")
        try:
            return ask(app.state.pool, deps, body.question, body.institution, body.user_institution,
                       body.as_of.isoformat() if body.as_of else None)
        finally:
            app.state.qa_slots.release()

    @app.get("/api/v1/alerts")
    def alerts(status: str = Query("open", pattern="^(open|done|NEW|ACKED|ACTION_REQUIRED|NO_ACTION|RESOLVED)$"),
               institution: str | None = None, severity: str | None = Query(None, pattern="^(HIGH|MEDIUM|LOW)$"),
               c=Depends(conn)):
        from reg.alerts.inbox import list_alerts

        return list_alerts(c, status, institution, severity)

    @app.get("/api/v1/alerts/{impact_id}")
    def alert(impact_id: int, c=Depends(conn)):
        from reg.alerts.inbox import alert_detail

        d = alert_detail(c, impact_id)
        if d is None:
            raise HTTPException(404, "알림을 찾을 수 없습니다")
        return d

    @app.post("/api/v1/alerts/{impact_id}/status")
    def alert_status(impact_id: int, body: AlertStatusIn, c=Depends(conn)):
        from reg.alerts.inbox import set_status

        if body.status == "NO_ACTION" and not (body.note or "").strip():
            raise HTTPException(422, "조치 불필요는 사유가 필요합니다")
        if not set_status(c, impact_id, body.status, body.note):
            raise HTTPException(404, "알림을 찾을 수 없습니다")
        return {"ok": True}

    @app.post("/api/v1/qa/{qa_id}/feedback")
    def qa_feedback(qa_id: int, body: FeedbackIn, c=Depends(conn)):
        n = c.execute("UPDATE ops.qa_log SET feedback = %s WHERE id = %s",
                      (body.feedback + (f": {body.reason[:300]}" if body.reason else ""), qa_id)).rowcount
        c.commit()
        if not n:
            raise HTTPException(404, "질의 기록을 찾을 수 없습니다")
        return {"ok": True}

    from reg.api.law_routes import router as law_router  # M6-1 법령 미러
    app.include_router(law_router)
    from reg.api.provision_routes import router as provision_router  # 참조 팝업

    app.include_router(provision_router)
    from reg.api.graph_routes import router as graph_router  # M7-G 구조 그래프

    app.include_router(graph_router)
    app.include_router(compare_router)  # 기관 비교 (UI 개편 §4)
    return app
