"""release 빌드 (spec 6.2): 청크 → (묶음마다) 캐시 조회·없는 것만 임베딩 → bulk → 건수 확인.
모든 벡터를 한꺼번에 들고 있지 않는다. 게시는 release.publish_release가 한다."""
import json

from reg.index.cache import embed_cached, text_hash
from reg.index.chunks import chunk_version
from reg.index.mapping import ALIAS
from reg.index.release import publish_release

BULK = 500

VERSIONS_SQL = (
    "SELECT v.id, v.work_id, v.title, v.effective_from, v.effective_to, v.version_state, w.kind,"
    " w.status AS work_status, w.abolished_on, i.code AS institution"
    " FROM regulation.work_version v JOIN regulation.work w ON w.id = v.work_id"
    " LEFT JOIN regulation.institution i ON i.id = w.institution_id WHERE v.version_state <> 'UNDATED'"
    " ORDER BY v.id")


def _provisions(conn, version_id: str) -> list[dict]:
    return conn.execute(
        "SELECT pv.path, pv.unit, pv.number_label AS label, pv.heading, pv.text, pv.parent_path AS parent"
        " FROM regulation.version_provision vp JOIN regulation.provision_version pv ON pv.id = vp.provision_version_id"
        " WHERE vp.work_version_id = %s ORDER BY vp.ord", (version_id,)).fetchall()


def doc_state(v: dict):
    """색인 문서의 (version_state, effective_to). Task 3에서 폐지 규칙을 넣는다."""
    return v["version_state"], v["effective_to"]


def fingerprint(conn, model_name: str) -> str:
    """Task 3에서 구현한다. 그 전까지는 건너뛰기가 일어나지 않도록 빈 문자열."""
    return ""


def _last_published(conn) -> dict | None:
    return conn.execute("SELECT id, os_index, stats FROM ops.release WHERE state = 'PUBLISHED'"
                        " ORDER BY published_at DESC NULLS LAST, id DESC LIMIT 1").fetchone()


def _flush(conn, os, embedder, model_name: str, index: str, batch: list[tuple[str, dict]], create: bool) -> int:
    vecs, miss = embed_cached(conn, embedder, model_name, {h: d["text"] for h, d in batch})
    if create:
        os.put_pipeline()
        os.create_index(index, len(next(iter(vecs.values()))))
    os.bulk(index, [{**d, "embedding": vecs[h]} for h, d in batch])
    return miss


def build_release(conn, os, embedder, model_name: str, publish: bool = True, force: bool = False) -> dict:
    fp = fingerprint(conn, model_name)
    last = _last_published(conn)
    if fp and not force and last and (last["stats"] or {}).get("fingerprint") == fp:
        conn.rollback()
        return {"skipped": True, "release_id": last["id"], "index": last["os_index"], "fingerprint": fp}
    rid = conn.execute("INSERT INTO ops.release (state, os_index, embedding_model) VALUES ('BUILDING', '', %s)"
                       " RETURNING id", (model_name,)).fetchone()["id"]
    index = f"{ALIAS}-r{rid}"
    conn.execute("UPDATE ops.release SET os_index = %s WHERE id = %s", (index, rid))
    conn.commit()
    try:
        versions = conn.execute(VERSIONS_SQL).fetchall()
        chunks, embedded, abolished = 0, 0, 0
        hashes: set[str] = set()
        batch: list[tuple[str, dict]] = []
        for v in versions:
            state, eff_to = doc_state(v)
            abolished += state == "ABOLISHED"
            for c in chunk_version(v["id"], v["work_id"], v["title"], _provisions(conn, v["id"])):
                h = text_hash(c.text)
                hashes.add(h)
                batch.append((h, {"chunk_id": c.chunk_id, "release_id": str(rid), "work_id": c.work_id,
                                  "version_id": c.version_id, "path": c.path, "path_label": c.path_label,
                                  "institution": v["institution"], "work_kind": v["kind"], "title": v["title"],
                                  "text": c.text, "context_text": c.context_text,
                                  "effective_from": v["effective_from"].isoformat() if v["effective_from"] else None,
                                  "effective_to": eff_to.isoformat() if eff_to else None,
                                  "version_state": state, "embedding_model": model_name}))
                if len(batch) >= BULK:
                    embedded += _flush(conn, os, embedder, model_name, index, batch, create=chunks == 0)
                    chunks += len(batch)
                    batch = []
        if batch:
            embedded += _flush(conn, os, embedder, model_name, index, batch, create=chunks == 0)
            chunks += len(batch)
        if chunks == 0:
            os.put_pipeline()
            os.create_index(index, embedder.dim or 1024)
        os.refresh(index)
        if os.count(index) != chunks:
            raise RuntimeError(f"색인 건수 불일치 {os.count(index)} != {chunks}")
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO ops.release_item (release_id, work_version_id) VALUES (%s, %s)",
                            [(rid, v["id"]) for v in versions])
        stats = {"chunks": chunks, "unique_texts": len(hashes), "embedded": embedded, "versions": len(versions),
                 "abolished": abolished, "fingerprint": fp, "built": True}
        conn.execute("UPDATE ops.release SET stats = %s WHERE id = %s", (json.dumps(stats), rid))
        conn.commit()
    except Exception as e:
        conn.rollback()
        os.delete_index(index)              # 아직 alias가 가리킨 적 없는 색인만 여기서 지운다 (404는 무시됨)
        conn.execute("UPDATE ops.release SET state = 'FAILED', error = %s WHERE id = %s",
                     (f"{type(e).__name__}: {e}"[:2000], rid))
        conn.commit()
        raise
    out = {"skipped": False, "release_id": rid, "index": index, **stats}
    if publish:                              # 게시 실패는 빌드 실패가 아니다: 색인을 지우지 않는다
        publish_release(conn, os, rid, require_gate=False)
    return out
