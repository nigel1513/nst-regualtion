"""기관 비교 API (서비스 UI 개편 spec §2·§4). 데이터는 reg topics classify · reg compare build가 만든다."""
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from reg.compare import queries as CQ
from reg.compare.config import load

router = APIRouter()
CODE = r"^[A-Za-z0-9]+(,[A-Za-z0-9]+)*$"


def _codes(c, raw: str | None) -> list[str] | None:
    if not raw:
        return None
    codes = list(dict.fromkeys(x.strip().upper() for x in raw.split(",") if x.strip()))
    known = {i["code"] for i in CQ.institutions(c)}
    if bad := [x for x in codes if x not in known]:
        raise HTTPException(400, f"알 수 없는 기관: {', '.join(bad)}")
    return codes


def _topic(cfg, topic: str) -> None:
    if not cfg.has_topic(topic):
        raise HTTPException(404, "주제를 찾을 수 없습니다")


@router.get("/api/v1/topics")
def topics(request: Request, inst: str | None = Query(None, pattern=r"^[A-Za-z0-9]+$")):
    with request.app.state.pool.connection() as c:
        if inst:
            _codes(c, inst)
        return CQ.topics(c, load(), inst.upper() if inst else None)


@router.get("/api/v1/compare")
def compare(request: Request, topic: str, inst: str | None = Query(None, pattern=CODE),
            ours: str | None = Query(None, pattern=r"^[A-Za-z0-9]+$")):
    cfg = load()
    _topic(cfg, topic)
    with request.app.state.pool.connection() as c:
        codes = _codes(c, inst)
        ours = (_codes(c, ours) or [None])[0]
        return CQ.compare(c, cfg, topic, codes, ours)


@router.get("/api/v1/compare/divergences")
def divergences(request: Request, inst: str = Query(..., pattern=r"^[A-Za-z0-9]+$"), limit: int = Query(10, ge=1, le=50)):
    with request.app.state.pool.connection() as c:
        code = _codes(c, inst)[0]
        return CQ.divergences(c, load(), code, limit)


@router.get("/api/v1/compare/provisions")
def provisions(request: Request, topic: str, item: str, inst: str | None = Query(None, pattern=CODE),
               ours: str | None = Query(None, pattern=r"^[A-Za-z0-9]+$")):
    cfg = load()
    _topic(cfg, topic)
    if not any(i.id == item for i in cfg.items.get(topic, [])):
        raise HTTPException(404, "비교 항목을 찾을 수 없습니다")
    with request.app.state.pool.connection() as c:
        return CQ.provisions(c, cfg, topic, item, _codes(c, inst), (_codes(c, ours) or [None])[0])


@router.get("/api/v1/compare/export.csv")
def export_csv(request: Request, topic: str | None = None, inst: str | None = Query(None, pattern=CODE)):
    cfg = load()
    if topic:
        _topic(cfg, topic)
    with request.app.state.pool.connection() as c:
        body = CQ.export_csv(c, cfg, topic, _codes(c, inst))
    name = f"compare-{topic or 'all'}.csv"
    return Response(body, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
