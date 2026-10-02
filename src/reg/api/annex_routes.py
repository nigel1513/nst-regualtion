# src/reg/api/annex_routes.py
"""별표·별지 원문 이미지·표 API (M6-6). app.py에는 include_router 한 줄만 더한다 (overview §3)."""
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from reg.core.annex import ensure_rendered, image_key
from reg.core.annex_tables import table_key

router = APIRouter()
PATH_RE = r"^(?:annex|form)\d+(?:-\d+)?(?:~\d+)?$"


def _conn(request: Request):
    with request.app.state.pool.connection() as c:
        yield c


def _item(request: Request, c, version: str, path: str) -> tuple[str, dict]:
    row = c.execute("SELECT sd.sha256 FROM regulation.work_version v JOIN regulation.source_document sd"
                    " ON sd.id = v.source_document_id WHERE v.id = %s", (version,)).fetchone()
    if not row:
        raise HTTPException(404, "버전을 찾을 수 없습니다")
    item = ensure_rendered(c, request.app.state.blob, version).get("items", {}).get(path)
    if not item:
        raise HTTPException(404, "이 별표는 보기용 PDF나 원문 위치가 없어 이미지가 없습니다")
    return row["sha256"], item


def _url(kind: str, **q) -> str:
    return f"/api/v1/annex/{kind}?{urlencode(q)}"


@router.get("/api/v1/annex")
def annex(request: Request, version: str, path: str = Query(..., pattern=PATH_RE), c=Depends(_conn)):
    _, item = _item(request, c, version, path)
    segs = [{"n": n, "page": s["page"], "url": _url("image", version=version, path=path, n=n)}
            for n, s in enumerate(item["segments"], 1)]
    status = item.get("table", {}).get("status", "none")
    return {"version": version, "path": path, "page": segs[0]["page"], "segments": segs,
            "table": {"status": status, "url": _url("table", version=version, path=path) if status == "ok" else None}}


@router.get("/api/v1/annex/image")
def annex_image(request: Request, version: str, path: str = Query(..., pattern=PATH_RE), n: int = Query(1, ge=1),
                c=Depends(_conn)):
    sha, item = _item(request, c, version, path)
    if n > len(item["segments"]):
        raise HTTPException(404, "그런 조각이 없습니다")
    return Response(request.app.state.blob.get(image_key(sha, path, n)), media_type="image/png",
                    headers={"Cache-Control": "private, max-age=86400"})


@router.get("/api/v1/annex/table")
def annex_table(request: Request, version: str, path: str = Query(..., pattern=PATH_RE), c=Depends(_conn)):
    sha, item = _item(request, c, version, path)
    if item.get("table", {}).get("status") != "ok":
        raise HTTPException(404, "표로 변환한 결과가 없습니다")
    return {"html": request.app.state.blob.get(table_key(sha, path)).decode("utf-8")}
