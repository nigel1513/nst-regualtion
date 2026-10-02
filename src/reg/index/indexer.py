"""게시 버전 빌드: 청크 → 임베딩(중복 제거) → 새 인덱스 → 확인 → 별칭 전환 (spec 7)."""
import hashlib
import json

from reg.index.chunks import chunk_version
from reg.index.mapping import ALIAS
from reg.index.os import OpenSearch

BULK = 500


def _versions(conn) -> list[dict]:
    return conn.execute(
        "SELECT v.id, v.work_id, v.title, v.effective_from, v.effective_to, v.version_state, w.kind,"
        " i.code AS institution FROM regulation.work_version v JOIN regulation.work w ON w.id = v.work_id"
        " LEFT JOIN regulation.institution i ON i.id = w.institution_id WHERE v.version_state <> 'UNDATED'"
        " ORDER BY v.id").fetchall()


def _provisions(conn, version_id: str) -> list[dict]:
    return conn.execute(
        "SELECT pv.path, pv.unit, pv.number_label AS label, pv.heading, pv.text, pv.parent_path AS parent"
        " FROM regulation.version_provision vp JOIN regulation.provision_version pv ON pv.id = vp.provision_version_id"
        " WHERE vp.work_version_id = %s ORDER BY vp.ord", (version_id,)).fetchall()


def build_release(conn, os: OpenSearch, embedder, model_name: str, publish: bool = True) -> dict:
    rid = conn.execute("INSERT INTO ops.release (state, os_index, embedding_model) VALUES ('BUILDING', '', %s)"
                       " RETURNING id", (model_name,)).fetchone()["id"]
    index = f"{ALIAS}-r{rid}"
    conn.execute("UPDATE ops.release SET os_index = %s WHERE id = %s", (index, rid))
    conn.commit()
    created = False
    try:
        versions = _versions(conn)
        docs, texts = [], {}
        for v in versions:
            for c in chunk_version(v["id"], v["work_id"], v["title"], _provisions(conn, v["id"])):
                h = hashlib.sha256(c.text.encode()).hexdigest()
                texts.setdefault(h, c.text)
                docs.append((h, {"chunk_id": c.chunk_id, "release_id": str(rid), "work_id": c.work_id,
                                 "version_id": c.version_id, "path": c.path, "path_label": c.path_label,
                                 "institution": v["institution"], "work_kind": v["kind"], "title": v["title"],
                                 "text": c.text, "context_text": c.context_text,
                                 "effective_from": v["effective_from"].isoformat() if v["effective_from"] else None,
                                 "effective_to": v["effective_to"].isoformat() if v["effective_to"] else None,
                                 "version_state": v["version_state"], "embedding_model": model_name}))
        keys = list(texts)
        vecs = dict(zip(keys, embedder.embed([texts[k] for k in keys])))
        dim = len(next(iter(vecs.values()))) if vecs else (embedder.dim or 1024)
        os.put_pipeline()
        os.create_index(index, dim)
        created = True
        batch = []
        for h, d in docs:
            d["embedding"] = vecs[h]
            batch.append(d)
            if len(batch) >= BULK:
                os.bulk(index, batch)
                batch = []
        os.bulk(index, batch)
        os.refresh(index)
        if os.count(index) != len(docs):
            raise RuntimeError(f"색인 건수 불일치 {os.count(index)} != {len(docs)}")
        for v in versions:
            conn.execute("INSERT INTO ops.release_item (release_id, work_version_id) VALUES (%s, %s)",
                         (rid, v["id"]))
        stats = {"chunks": len(docs), "unique_texts": len(keys), "versions": len(versions)}
        if publish:
            os.swap_alias(index)
            conn.execute("UPDATE ops.release SET state = 'RETIRED' WHERE state = 'PUBLISHED'")
            conn.execute("UPDATE ops.release SET state = 'PUBLISHED', published_at = now(), stats = %s"
                         " WHERE id = %s", (json.dumps(stats), rid))
        else:
            conn.execute("UPDATE ops.release SET stats = %s WHERE id = %s", (json.dumps(stats), rid))
        conn.commit()
        return {"release_id": rid, "index": index, **stats}
    except Exception as e:
        conn.rollback()
        if created:
            os.delete_index(index)
        conn.execute("UPDATE ops.release SET state = 'FAILED', error = %s WHERE id = %s",
                     (f"{type(e).__name__}: {e}"[:2000], rid))
        conn.commit()
        raise
