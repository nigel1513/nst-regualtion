# src/reg/api/annex_routes.py
"""별표·별지 원문 이미지·표 API (M6-6). app.py에는 include_router 한 줄만 더한다 (overview §3)."""
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from reg.core.annex import image_key, render_order, version_order
from reg.core.annex_tables import table_key

router = APIRouter()
PATH_RE = r"^(?:annex|form)\d+(?:-\d+)?(?:~\d+)?$"


def _item(request: Request, version: str, path: str) -> tuple[str, dict]:
    """DB는 판본 정보만 읽고 바로 돌려준다. 이미지는 연결 없이 그린다(별표가 많은 판본의 첫 화면이 풀을 막지 않게)."""
    with request.app.state.pool.connection() as c:
        sd, order = version_order(c, version)
    if not sd:
        raise HTTPException(404, "버전을 찾을 수 없습니다")
    item = render_order(request.app.state.blob, sd, order).get("items", {}).get(path)
    if not item:
        raise HTTPException(404, "이 별표는 보기용 PDF나 원문 위치가 없어 이미지가 없습니다")
    return sd["sha256"], item


def _url(kind: str, **q) -> str:
    return f"/api/v1/annex/{kind}?{urlencode(q)}"


@router.get("/api/v1/annex")
def annex(request: Request, version: str, path: str = Query(..., pattern=PATH_RE)):
    _, item = _item(request, version, path)
    segs = [{"n": n, "page": s["page"], "url": _url("image", version=version, path=path, n=n)}
            for n, s in enumerate(item["segments"], 1)]
    status = item.get("table", {}).get("status", "none")
    return {"version": version, "path": path, "page": segs[0]["page"], "segments": segs,
            "table": {"status": status, "url": _url("table", version=version, path=path) if status == "ok" else None}}


@router.get("/api/v1/annex/image")
def annex_image(request: Request, version: str, path: str = Query(..., pattern=PATH_RE), n: int = Query(1, ge=1)):
    sha, item = _item(request, version, path)
    if n > len(item["segments"]):
        raise HTTPException(404, "그런 조각이 없습니다")
    return Response(request.app.state.blob.get(image_key(sha, path, n)), media_type="image/png",
                    headers={"Cache-Control": "private, max-age=86400"})


@router.get("/api/v1/annex/table")
def annex_table(request: Request, version: str, path: str = Query(..., pattern=PATH_RE)):
    sha, item = _item(request, version, path)
    if item.get("table", {}).get("status") != "ok":
        raise HTTPException(404, "표로 변환한 결과가 없습니다")
    return {"html": request.app.state.blob.get(table_key(sha, path)).decode("utf-8")}
