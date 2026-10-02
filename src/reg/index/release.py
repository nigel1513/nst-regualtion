"""release 게시·게이트·정리 (spec 6.2). 원칙: alias를 바꾼 뒤에는 어떤 실패에도 색인을 지우지 않는다."""
import logging

log = logging.getLogger(__name__)


def _release(conn, release_id: int) -> dict:
    r = conn.execute("SELECT id, state, os_index, stats FROM ops.release WHERE id = %s", (release_id,)).fetchone()
    if r is None:
        raise ValueError(f"release {release_id} 없음")
    return r


def publish_release(conn, os, release_id: int, require_gate: bool = True) -> dict:
    r = _release(conn, release_id)
    if r["state"] == "PUBLISHED":
        conn.rollback()
        return {"release_id": r["id"], "index": r["os_index"], "published": True, "already": True,
                "previous_index": None}
    stats = r["stats"] or {}
    if r["state"] != "BUILDING" or not stats.get("built"):
        raise RuntimeError(f"release {release_id} 상태 {r['state']}: 게시할 수 없음")
    if require_gate and not (stats.get("gate") or {}).get("passed"):
        raise RuntimeError(f"release {release_id}: 품질 게이트를 통과하지 않음")
    if os.count(r["os_index"]) != stats.get("chunks"):
        raise RuntimeError(f"release {release_id}: 색인 {r['os_index']} 건수가 빌드 기록과 다름")
    conn.execute("UPDATE ops.release SET state = 'RETIRED' WHERE state = 'PUBLISHED'")
    conn.execute("UPDATE ops.release SET state = 'PUBLISHED', published_at = now() WHERE id = %s", (release_id,))
    try:
        old = os.swap_alias(r["os_index"])
    except Exception:
        conn.rollback()                     # alias가 안 바뀌었으니 DB도 그대로. 색인은 남겨 재시도한다.
        raise
    try:
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        finally:
            if old:                          # DB가 아직 old를 게시본으로 알고 있으므로 alias도 되돌린다
                try:
                    os.swap_alias(old)
                except Exception:            # 되돌리기도 실패하면 새 색인이 계속 서비스된다(지우지 않으므로 검색은 된다)
                    log.exception("alias 되돌리기 실패: %s 유지", r["os_index"])
        raise
    return {"release_id": r["id"], "index": r["os_index"], "published": True, "already": False,
            "previous_index": old}
