"""임베딩 캐시 (spec 6.2): 청크 텍스트 해시 + 모델로 찾고, 없는 것만 임베딩해 넣는다.
모델이 바뀌면 키가 달라져 캐시가 자연히 갈린다."""
import hashlib


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def lookup(conn, model: str, hashes: list[str]) -> dict[str, list[float]]:
    if not hashes:
        return {}
    rows = conn.execute("SELECT text_hash, vector FROM ops.embedding_cache WHERE model = %s AND text_hash = ANY(%s)",
                        (model, hashes)).fetchall()
    return {r["text_hash"]: list(r["vector"]) for r in rows}


def store(conn, model: str, vecs: dict[str, list[float]]) -> None:
    if not vecs:
        return
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO ops.embedding_cache (text_hash, model, vector) VALUES (%s, %s, %s::real[])"
                        " ON CONFLICT DO NOTHING", [(h, model, v) for h, v in vecs.items()])


def embed_cached(conn, embedder, model: str, texts: dict[str, str]) -> tuple[dict[str, list[float]], int]:
    """texts = {hash: text}. 캐시에 없는 것만 임베딩하고 캐시에 넣은 뒤 커밋한다.
    커밋하는 이유: 빌드가 뒤에서 실패(GPU 꺼짐)해도 이미 임베딩한 묶음은 재시도 때 다시 하지 않는다."""
    got = lookup(conn, model, list(texts))
    miss = [h for h in texts if h not in got]
    if miss:
        new = embedder.embed([texts[h] for h in miss])
        if len(new) != len(miss):
            raise RuntimeError(f"임베딩 수 불일치 {len(new)} != {len(miss)}")
        fresh = dict(zip(miss, new))
        store(conn, model, fresh)
        conn.commit()
        got.update(fresh)
    return got, len(miss)
