"""release 빌드 (spec 6.2, M7 §2.1): 조항 단위 문서 → (묶음마다) 캐시 조회·없는 것만 임베딩 → bulk → 건수 확인.
모든 벡터를 한꺼번에 들고 있지 않는다. 게시는 release.publish_release가 한다."""
import hashlib
import json
import time

from reg.index.cache import embed_cached, text_hash
from reg.index.mapping import ALIAS
from reg.index.release import LINE, publish_release
from reg.index.units import unit_docs

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
    " ORDER BY (v.version_state = 'CURRENT') DESC, v.id")   # 현행 먼저: 첫 묶음의 벡터로 색인 차원을 정한다


def _provisions(conn, version_id: str) -> list[dict]:
    return conn.execute(
        "SELECT pv.id, pv.path, pv.unit, pv.number_label AS label, pv.heading, pv.text, pv.parent_path AS parent"
        " FROM regulation.version_provision vp JOIN regulation.provision_version pv ON pv.id = vp.provision_version_id"
        " WHERE vp.work_version_id = %s ORDER BY vp.ord", (version_id,)).fetchall()


INDEX_FORMAT = "provisions-v1+abolished-v1+institution-v1"   # 청크·매핑·문서 필드 규칙이 바뀌면 올린다 → 지문이 달라져 다시 빌드

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
    return conn.execute(f"SELECT id, os_index, stats FROM ops.release WHERE state = 'PUBLISHED' AND {LINE}"
                        " ORDER BY published_at DESC NULLS LAST, id DESC LIMIT 1").fetchone()


class _Sink:
    """묶음을 받아 캐시 조회·임베딩·bulk 한다. 색인은 첫 벡터가 나온 묶음에서 그 차원으로 만든다."""

    def __init__(self, conn, os, embedder, model_name: str, index: str, embed_pause: float = 0.0):
        self.conn, self.os, self.embedder, self.model, self.index = conn, os, embedder, model_name, index
        self.pause, self.created, self.pending = embed_pause, False, []
        self.docs = self.vectors = self.embedded = 0
        self.hashes: set[str] = set()

    def add(self, doc: dict, embed_text: str | None) -> None:
        self.pending.append((doc, embed_text))

    def flush(self, final: bool = False) -> None:
        batch, self.pending = self.pending, []
        texts = {text_hash(t): t for _, t in batch if t}
        vecs: dict[str, list[float]] = {}
        if texts:
            vecs, miss = embed_cached(self.conn, self.embedder, self.model, texts)
            self.embedded += miss
            self.hashes |= set(texts)
            if miss and self.pause:
                time.sleep(self.pause)       # GPU를 운영 질의와 나눠 쓴다
        if not self.created:
            if not vecs and not final:       # 차원을 아직 모른다: 벡터가 나올 때까지 모은다
                self.pending = batch
                return
            self.os.put_pipeline()
            self.os.create_index(self.index, len(next(iter(vecs.values()))) if vecs else (self.embedder.dim or 1024))
            self.created = True
        docs = []
        for d, t in batch:
            if t:
                d = {**d, "embedding": vecs[text_hash(t)]}
                self.vectors += 1
            docs.append(d)
        self.os.bulk(self.index, docs)
        self.docs += len(docs)


def build_release(conn, os, embedder, model_name: str, publish: bool = True, force: bool = False,
                  embed_pause: float = 0.0) -> dict:
    t0 = time.monotonic()
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
        sink = _Sink(conn, os, embedder, model_name, index, embed_pause)
        abolished = 0
        for v in versions:
            state, eff_to = doc_state(v)
            abolished += state == "ABOLISHED"
            meta = {**v, "state": state, "effective_to": eff_to, "release_id": str(rid), "embedding_model": model_name}
            for u in unit_docs(meta, _provisions(conn, v["id"])):
                sink.add(u.doc, u.embed_text)
                if len(sink.pending) >= BULK:
                    sink.flush()
        sink.flush(final=True)
        docs = sink.docs
        os.refresh(index)
        if os.count(index) != docs:
            raise RuntimeError(f"색인 건수 불일치 {os.count(index)} != {docs}")
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO ops.release_item (release_id, work_version_id) VALUES (%s, %s)",
                            [(rid, v["id"]) for v in versions])
        stats = {"chunks": docs, "docs": docs, "vectors": sink.vectors, "unique_texts": len(sink.hashes),
                 "embedded": sink.embedded, "versions": len(versions), "abolished": abolished, "fingerprint": fp,
                 "built": True, "seconds": round(time.monotonic() - t0, 1)}
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
