"""법령·규정 구조 그래프 API (spec 2026-10-03 §1.3): 관계도·조항 이력·근거 확장.

드라이버는 app.state.graph_driver (없으면 설정에서 처음 요청 때 만든다). Neo4j 장애는 503."""
import logging
import threading
from datetime import date

from fastapi import APIRouter, HTTPException, Query, Request
from neo4j.exceptions import AuthError, ServiceUnavailable, SessionExpired, TransientError

from reg.graph.query import expand, lineage, neighborhood, today

router = APIRouter()
log = logging.getLogger(__name__)
_lock = threading.Lock()
GRAPH_DOWN = (ServiceUnavailable, SessionExpired, TransientError, AuthError)


def _driver(request: Request):
    st = request.app.state
    with _lock:
        if getattr(st, "graph_driver", None) is None:
            from reg.platform.neo4j import neo4j_driver

            st.graph_driver = neo4j_driver()
        return st.graph_driver


def _call(request: Request, fn, *args, **kw):
    try:
        return fn(_driver(request), *args, **kw)
    except GRAPH_DOWN as e:  # 그래프 장애는 503 (코드 오류는 그대로 500)
        log.warning("graph query failed: %s: %s", type(e).__name__, e)
        raise HTTPException(503, "그래프 서버에 연결할 수 없습니다") from e


@router.get("/api/v1/graph/neighborhood")
def graph_neighborhood(request: Request, pv: int, depth: int = Query(1, ge=1, le=2),
                       limit: int = Query(200, ge=10, le=500)):
    """이 조항이 근거하는 것·이 조항을 인용하는 것·용어 정의·판본 계보·상위/하위 조항 (노드·엣지)."""
    out = _call(request, neighborhood, pv, depth=depth, limit=limit)
    if out is None:
        raise HTTPException(404, "그래프에 그 조항이 없습니다")
    return out


@router.get("/api/v1/graph/lineage")
def graph_lineage(request: Request, pv: int):
    """조항 이력: 같은 조항의 판본들(시행일 순)과 각 개정 종류."""
    out = _call(request, lineage, pv)
    if out is None:
        raise HTTPException(404, "그래프에 그 조항이 없습니다")
    return out


@router.get("/api/v1/graph/expand")
def graph_expand(request: Request, pv: list[int] = Query(..., max_length=50), as_of: date | None = None,
                 depth: int = Query(1, ge=1, le=2), limit: int = Query(30, ge=1, le=100)):
    """근거 조항에서 예외·준용·근거·위임·인용 조항, 용어 정의, 상위 조를 이유와 함께."""
    as_of = as_of or today()
    return {"as_of": as_of.isoformat(), "items": _call(request, expand, pv, as_of=as_of, depth=depth, limit=limit)}
