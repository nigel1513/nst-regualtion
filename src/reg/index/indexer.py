"""release 빌드 (spec 6.2): 청크 → (묶음마다) 캐시 조회·없는 것만 임베딩 → bulk → 건수 확인.
모든 벡터를 한꺼번에 들고 있지 않는다. 게시는 release.publish_release가 한다."""
import hashlib
import json

from reg.index.cache import embed_cached, text_hash
from reg.index.chunks import chunk_version
from reg.index.mapping import ALIAS
from reg.index.release import publish_release

BULK = 500

# 법령·행정규칙은 기관 대신 institution='LAW', 이름은 소관부처(M6-1이 work.external_ids.ministry로 넘긴다)
IS_LAW = "(w.id LIKE 'kr/law/%' OR w.id LIKE 'kr/admrul/%')"

VERSIONS_SQL = (
    "SELECT v.id, v.work_id, v.title, v.effective_from, v.effective_to, v.version_state, w.kind,"
    " w.status AS work_status, w.abolished_on,"
    f" CASE WHEN {IS_LAW} THEN 'LAW' ELSE i.code END AS institution,"
    f" CASE WHEN {IS_LAW} THEN w.external_ids->>'ministry' ELSE i.name END AS institution_name,"
    f" CASE WHEN {IS_LAW} THEN '{{}}'::text[] ELSE coalesce(i.aliases, '{{}}') END AS institution_aliases"
    " FROM regulation.work_version v JOIN regulation.work w ON w.id = v.work_id"
    " LEFT JOIN regulation.institution i ON i.id = w.institution_id WHERE v.version_state <> 'UNDATED'"
    " ORDER BY v.id")


def _provisions(conn, version_id: str) -> list[dict]:
    return conn.execute(
        "SELECT pv.path, pv.unit, pv.number_label AS label, pv.heading, pv.text, pv.parent_path AS parent"
        " FROM regulation.version_provision vp JOIN regulation.provision_version pv ON pv.id = vp.provision_version_id"
        " WHERE vp.work_version_id = %s ORDER BY vp.ord", (version_id,)).fetchall()


INDEX_FORMAT = "chunks-v1+abolished-v1+institution-v1"   # 청크·매핑·문서 필드 규칙이 바뀌면 올린다 → 지문이 달라져 다시 빌드

FINGERPRINT_SQL = """
SELECT count(*) AS n, coalesce(md5(string_agg(concat_ws('|', v.id, v.title,
         coalesce(v.effective_from::text, '-'), coalesce(v.effective_to::text, '-'), v.version_state,
         coalesce(v.parser_version, '-'), w.kind, w.status, coalesce(w.abolished_on::text, '-'),
         coalesce(i.code, '-'), coalesce(i.name, '-'), coalesce(array_to_string(i.aliases, ','), '-'),
         coalesce(w.external_ids->>'ministry', '-'),
         (SELECT coalesce(md5(string_agg(vp.provision_version_id::text, ',' ORDER BY vp.ord)), '-')
            FROM regulation.version_provision vp WHERE vp.work_version_id = v.id)),
       E'\\n' ORDER BY v.id)), '') AS h
FROM regulation.work_version v JOIN regulation.work w ON w.id = v.work_id
LEFT JOIN regulation.institution i ON i.id = w.institution_id
WHERE v.version_state <> 'UNDATED'
"""


def fingerprint(conn, model_name: str) -> str:
    """마지막 게시 이후 색인 내용이 바뀔 수 있는 모든 입력의 지문 (spec 6.2 새 release 조건)."""
    r = conn.execute(FINGERPRINT_SQL).fetchone()
    return hashlib.sha256(f"{INDEX_FORMAT}|{model_name}|{r['n']}|{r['h']}".encode()).hexdigest()


def doc_state(v: dict):
    """폐지(ABOLISHED)된 규범문서: 현행·미래 버전을 ABOLISHED로, 시행 끝을 폐지일로 자른다.
    현행 검색(version_state=CURRENT)에서 빠지고, 폐지일 전 기준일 검색에서는 계속 찾힌다.
    폐지 후보(ABOLISHED_CANDIDATE)는 확정 전이므로 그대로 둔다."""
    state, to = v["version_state"], v["effective_to"]
    if v.get("work_status") != "ABOLISHED":
        return state, to
    end = v.get("abolished_on")
    if end is not None and (to is None or to > end):
        to = end
    if state in ("CURRENT", "FUTURE"):
        state = "ABOLISHED"
    return state, to


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
                                  "institution": v["institution"],
                                  "institution_name": v["institution_name"],
                                  "institution_aliases": list(v["institution_aliases"] or []), "work_kind": v["kind"], "title": v["title"],
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
