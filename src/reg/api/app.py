"""읽기 전용 규정 API (spec 10, NFR-02: LLM 없이 열람·검색)."""
from contextlib import asynccontextmanager
from datetime import date
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import Response
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from reg.api import queries as Q
from reg.storage.blob import BlobStore


def create_app(dsn: str, blob: BlobStore) -> FastAPI:
    pool = ConnectionPool(dsn, min_size=1, max_size=8, kwargs={"row_factory": dict_row}, open=False)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        pool.open()
        yield
        pool.close()

    app = FastAPI(title="NST 규정·법령 API", version="0.3", lifespan=lifespan)
    app.state.pool = pool
    app.state.blob = blob

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
    def view(id: str, as_of: date | None = None, c=Depends(conn)):
        w = _work_or_404(c, id)
        v = Q.pick_version(c, id, as_of)
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

    return app
