"""release 게시·게이트·정리 (spec 6.2). 원칙: alias를 바꾼 뒤에는 어떤 실패에도 색인을 지우지 않는다."""
import json
import logging
import re

from reg.index.mapping import ALIAS
from reg.index.service import search
from reg.platform.llm import ProviderError

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
        realigned = False
        if os.alias_target() != r["os_index"]:   # 커밋은 됐는데 응답을 잃어 alias를 되돌렸던 경우: DB가 기준
            os.swap_alias(r["os_index"])
            realigned = True
        return {"release_id": r["id"], "index": r["os_index"], "published": True, "already": True,
                "previous_index": None, "realigned": realigned}
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


MAX_DROP = 0.02
SMOKE_TOP = 5


def chunk_drop_ok(chunks: int, prev: int | None, max_drop: float = MAX_DROP) -> bool:
    """청크 수가 직전 게시본보다 max_drop 넘게 줄지 않았나 (대량 누락 방지). 정수 비교로 경계 오차를 없앤다."""
    if prev is None:
        return True
    return chunks * 100 >= prev * round((1 - max_drop) * 100)


def _article(path: str) -> str:
    return re.split(r"[.#]", path, maxsplit=1)[0]


def smoke_check(os, embedder, reranker, index: str, cases: list[dict], top: int = SMOKE_TOP) -> list[dict]:
    out = []
    for c in cases:
        r = search(os, embedder, reranker, c["query"], institution=c.get("institution"),
                   rerank=reranker is not None, size=top, index=index)
        hits = r["hits"][:top]
        hit = any(c["work_contains"] in h["work_id"] and _article(h["path"]) == c["article"] for h in hits)
        out.append({"id": c["id"], "hit": hit, "mode": r["mode"], "reranked": r["reranked"],
                    "top": [f"{h['work_id']}|{h['path']}" for h in hits]})
    return out


def gate_release(conn, os, embedder, reranker, release_id: int, smoke: list[dict],
                 max_drop: float = MAX_DROP) -> dict:
    if not smoke:
        raise ValueError("스모크 질의가 없다: config/index_smoke.yaml 확인")
    r = _release(conn, release_id)
    if r["state"] == "PUBLISHED":
        conn.rollback()
        return {"release_id": r["id"], "passed": True, "already_published": True,
                "chunks": (r["stats"] or {}).get("chunks"), "prev_chunks": None, "indexed": None, "reasons": [],
                "smoke": []}
    stats = r["stats"] or {}
    if r["state"] != "BUILDING" or not stats.get("built"):
        raise RuntimeError(f"release {release_id} 상태 {r['state']}: 게이트를 볼 수 없음 (다시 빌드)")
    prev = conn.execute("SELECT stats FROM ops.release WHERE state = 'PUBLISHED' AND id <> %s"
                        " ORDER BY published_at DESC NULLS LAST, id DESC LIMIT 1", (release_id,)).fetchone()
    chunks = stats["chunks"]
    prev_chunks = (prev["stats"] or {}).get("chunks") if prev else None
    indexed = os.count(r["os_index"])
    checks = smoke_check(os, embedder, reranker, r["os_index"], smoke)
    degraded = [c["id"] for c in checks
                if c["mode"] != "hybrid" or (reranker is not None and c["top"] and not c["reranked"])]
    if degraded:                            # 임베딩·재순위 서버 장애는 색인 품질이 아니다: FAILED로 두지 않고 재시도한다
        conn.rollback()
        raise ProviderError(f"release {release_id}: 게이트 검색이 하이브리드·재순위 없이 돌았다 ({', '.join(degraded)})")
    reasons = []
    if not chunk_drop_ok(chunks, prev_chunks, max_drop):
        reasons.append(f"청크 수 {chunks} < 직전 {prev_chunks} × {1 - max_drop:.2f}")
    if indexed != chunks:
        reasons.append(f"색인 건수 {indexed} != 빌드 기록 {chunks}")
    missed = [c["id"] for c in checks if not c["hit"]]
    if missed:
        reasons.append(f"스모크 실패: {', '.join(missed)}")
    result = {"release_id": r["id"], "passed": not reasons, "already_published": False, "chunks": chunks,
              "prev_chunks": prev_chunks, "indexed": indexed, "reasons": reasons, "smoke": checks}
    gate = json.dumps({"gate": {k: result[k] for k in ("passed", "chunks", "prev_chunks", "indexed", "reasons", "smoke")}},
                      ensure_ascii=False)
    if reasons:
        conn.execute("UPDATE ops.release SET state = 'FAILED', error = %s, stats = stats || %s::jsonb WHERE id = %s",
                     (("gate: " + "; ".join(reasons))[:2000], gate, release_id))
    else:
        conn.execute("UPDATE ops.release SET stats = stats || %s::jsonb WHERE id = %s", (gate, release_id))
    conn.commit()
    return result


RELEASE_INDEX = re.compile(rf"{re.escape(ALIAS)}-r\d+")


def prune_releases(conn, os, keep_building_hours: int = 6, dry_run: bool = False) -> dict:
    """게시본과 직전 게시본만 남긴다 (spec 6.2 정리). 진행 중인 빌드와 지금 alias 대상은 언제나 남긴다.
    색인 목록을 먼저 읽고 DB·alias를 나중에 읽어, 그 사이 만들어지거나 게시된 색인을 지우지 않는다."""
    names = os.indexes()
    cur = conn.execute("SELECT os_index FROM ops.release WHERE state = 'PUBLISHED'"
                       " ORDER BY published_at DESC NULLS LAST, id DESC LIMIT 1").fetchone()
    prev = conn.execute("SELECT os_index FROM ops.release WHERE state = 'RETIRED' AND published_at IS NOT NULL"
                        " ORDER BY published_at DESC, id DESC LIMIT 1").fetchone()
    building = conn.execute("SELECT os_index FROM ops.release WHERE state = 'BUILDING'"
                            " AND created_at > now() - make_interval(hours => %s)", (keep_building_hours,)).fetchall()
    stale_rows = conn.execute(
        "SELECT id, os_index FROM ops.release WHERE state = 'BUILDING'"
        " AND created_at <= now() - make_interval(hours => %s) ORDER BY id", (keep_building_hours,)).fetchall()
    keep = {r["os_index"] for r in (cur, prev, *building) if r}
    alias = os.alias_target()
    if alias:
        keep.add(alias)
    stale = [r["id"] for r in stale_rows]
    if dry_run:
        conn.rollback()
    else:
        if stale:                           # 그 사이 게시·실패 처리된 release는 건드리지 않는다
            done = conn.execute("UPDATE ops.release SET state = 'FAILED', error = 'stale: 빌드가 끝나지 않아 정리됨'"
                                " WHERE id = ANY(%s) AND state = 'BUILDING' RETURNING id", (stale,)).fetchall()
            moved = {r["id"] for r in done}
            keep |= {r["os_index"] for r in stale_rows if r["id"] not in moved}
            stale = [i for i in stale if i in moved]
        conn.commit()
        alias = os.alias_target()
        if alias:
            keep.add(alias)
    drop = [n for n in names if RELEASE_INDEX.fullmatch(n) and n not in keep]
    if not dry_run:
        for n in drop:
            os.delete_index(n)
    return {"kept": sorted(keep), "deleted": drop, "stale_failed": stale, "dry_run": dry_run}
