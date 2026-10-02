"""ocr.needed.v1 소비: 원본 PDF → OCR 줄·원본 결과 보관 → source_document 갱신 → 원래 수집 이벤트 재대기.

다시 파싱은 core 처리기(reg process)가 한다. 처리기는 ocr_blob_key가 있으면 OCR 줄로 읽고, 성공하면 LOW_TEXT를 닫는다.
OCR은 이벤트를 잡은 트랜잭션 안에서 기다린다(작업자 하나 전제, 죽으면 롤백되어 이벤트가 남는다).
GPU PC가 꺼져 있으면(OcrUnavailable) 시도 횟수를 올리지 않고 멈춘다 (계획 R6).
"""
import json

from reg.core.extract import extract
from reg.platform import outbox
from reg.platform.ocr import OcrEngine, OcrError, OcrUnavailable, dump_lines
from reg.platform.ocr_hooks import TOPIC, low_text_reason, request_ocr
from reg.platform.storage.blob import BlobStore

MAX_ATTEMPTS = 2
SOURCE_TOPICS = ["regulation.source_fetched"]


def ocr_key(sha256: str) -> str:
    return f"ocr/{sha256}.lines.json"


def raw_key(sha256: str) -> str:
    return f"ocr/{sha256}.middle.json"


def md_key(sha256: str) -> str:
    return f"ocr/{sha256}.md"


def requeue(conn, topic: str, payload: dict) -> int:
    n = conn.execute("UPDATE ops.outbox SET processed_at = NULL, claimed_at = NULL, attempts = 0, last_error = NULL"
                     " WHERE topic = %s AND payload->>'source_document_id' = %s",
                     (topic, str(payload["source_document_id"]))).rowcount
    if n == 0:
        outbox.write(conn, topic, payload)
        n = 1
    return n


def _note(conn, source_document_id: int, note: dict, upsert: bool = False) -> None:
    detail = json.dumps({"ocr": note}, ensure_ascii=False)
    if upsert:
        conn.execute("INSERT INTO regulation.review_task (kind, target, detail) VALUES ('LOW_TEXT', %s, %s)"
                     " ON CONFLICT (kind, target) DO UPDATE SET detail = regulation.review_task.detail || EXCLUDED.detail",
                     (f"source:{source_document_id}", detail))
    else:
        conn.execute("UPDATE regulation.review_task SET detail = detail || %s::jsonb"
                     " WHERE kind = 'LOW_TEXT' AND target = %s", (detail, f"source:{source_document_id}"))


def _done(conn, event_id: int, error: str | None = None) -> None:
    conn.execute("UPDATE ops.outbox SET processed_at = now(), claimed_at = now(), last_error = %s WHERE id = %s",
                 (error, event_id))


def _one(conn, blob: BlobStore, engine: OcrEngine, ev: dict) -> tuple[str, int]:
    """이벤트 하나. ('ready'|'retry'|'failed'|'skipped', 재대기한 수). OcrUnavailable은 호출자에게 그대로 올린다."""
    p = ev["payload"]
    sd = conn.execute("SELECT id, sha256, blob_key, mime, ocr_status, ocr_blob_key FROM regulation.source_document"
                      " WHERE id = %s", (p["source_document_id"],)).fetchone()
    if sd is None or sd["mime"] != "application/pdf":
        _done(conn, ev["id"], "PDF 원본이 아님")
        return "skipped", 0
    if sd["ocr_status"] == "ready" and sd["ocr_blob_key"]:  # 이미 OCR함: 다시 파싱만 시킨다
        n = requeue(conn, p["topic"], p["payload"])
        _done(conn, ev["id"])
        return "skipped", n
    try:
        res = engine.ocr(blob.get(sd["blob_key"]))
    except OcrError as e:
        conn.execute("UPDATE ops.outbox SET attempts = attempts + 1, claimed_at = now(), last_error = %s WHERE id = %s",
                     (f"OcrError: {e}"[:2000], ev["id"]))
        if ev["attempts"] + 1 < MAX_ATTEMPTS:
            return "retry", 0
        conn.execute("UPDATE regulation.source_document SET ocr_status = 'failed', ocr_engine = %s WHERE id = %s",
                     (engine.name, sd["id"]))
        _note(conn, sd["id"], {"status": "failed", "engine": engine.name, "error": str(e)[:500]}, upsert=True)
        return "failed", 0
    key = ocr_key(sd["sha256"])
    blob.put(key, dump_lines(res.lines), "application/json")
    blob.put(raw_key(sd["sha256"]), json.dumps(res.raw, ensure_ascii=False).encode("utf-8"), "application/json")
    blob.put(md_key(sd["sha256"]), res.markdown.encode("utf-8"), "text/markdown; charset=utf-8")
    conn.execute("UPDATE regulation.source_document SET ocr_status = 'ready', ocr_blob_key = %s, ocr_engine = %s"
                 " WHERE id = %s", (key, res.engine, sd["id"]))
    _note(conn, sd["id"], {"status": "ready", "engine": res.engine, "lines": len(res.lines)})
    n = requeue(conn, p["topic"], p["payload"])
    _done(conn, ev["id"])
    return "ready", n


def run_pending(conn, blob: BlobStore, engine: OcrEngine, limit: int = 50) -> dict:
    """대기 중인 ocr.needed.v1을 하나씩 처리하고 이벤트마다 커밋한다.

    - 대기가 있을 때만 엔진 상태를 먼저 확인한다. 꺼져 있으면 아무것도 잡지 않는다.
    - 한 실행에서 같은 이벤트는 한 번만 시도한다.
    - 도중에 서비스가 사라지면 그 이벤트를 롤백하고 멈춘다.
    """
    st = {"claimed": 0, "ready": 0, "retry": 0, "failed": 0, "skipped": 0, "requeued": 0, "processed": 0,
          "unavailable": False}
    queued = conn.execute("SELECT 1 FROM ops.outbox WHERE topic = %s AND processed_at IS NULL AND attempts < %s LIMIT 1",
                          (TOPIC, MAX_ATTEMPTS)).fetchone()
    conn.rollback()
    if queued is None:
        return st
    if not engine.available():
        st["unavailable"] = True
        return st
    tried: list[int] = []
    while st["claimed"] < limit:
        ev = conn.execute("SELECT id, payload, attempts FROM ops.outbox WHERE topic = %s AND processed_at IS NULL"
                          " AND attempts < %s AND NOT (id = ANY(%s::bigint[])) ORDER BY id LIMIT 1"
                          " FOR UPDATE SKIP LOCKED", (TOPIC, MAX_ATTEMPTS, tried)).fetchone()
        if ev is None:
            break
        tried.append(ev["id"])
        st["claimed"] += 1
        try:
            result, n = _one(conn, blob, engine, ev)
        except OcrUnavailable:
            conn.rollback()  # 이벤트·상태를 건드리지 않는다: 시도로 세지 않고 다음 실행에서 다시
            st["unavailable"] = True
            break
        st[result] += 1
        st["requeued"] += n
        st["processed"] += 1 if n else 0  # 다시 파싱할 것이 생김 → M6-3이 reg_process를 깨운다
        conn.commit()
    conn.commit()
    return st


def enqueue_low_text(conn, blob: BlobStore, dry_run: bool = False) -> dict:
    """M6-5 이전에 쌓인 원본 단위 LOW_TEXT(열림, ocr_status NULL)를 처리기와 같은 판정으로 OCR 대기열에 넣는다.

    판본 단위 LOW_TEXT(target이 'source:'가 아닌 것)는 범위 밖이라 세기만 한다(계획 R8).
    """
    st = {"pending": 0, "not_needed": 0, "no_event": 0, "unreadable": 0, "non_pdf": 0, "version_level": 0}
    st["version_level"] = conn.execute(
        "SELECT count(*) AS n FROM regulation.review_task WHERE kind = 'LOW_TEXT' AND status = 'OPEN'"
        " AND left(target, 7) <> 'source:'").fetchone()["n"]
    rows = conn.execute(
        "SELECT sd.id, sd.mime, sd.blob_key, sd.ocr_status FROM regulation.review_task t"
        " JOIN regulation.source_document sd ON t.target = 'source:' || sd.id"
        " WHERE t.kind = 'LOW_TEXT' AND t.status = 'OPEN' AND sd.ocr_status IS NULL ORDER BY sd.id").fetchall()
    for sd in rows:
        if sd["mime"] != "application/pdf":
            st["non_pdf"] += 1
            continue
        ev = conn.execute("SELECT topic, payload FROM ops.outbox WHERE topic = ANY(%s)"
                          " AND payload->>'source_document_id' = %s ORDER BY id DESC LIMIT 1",
                          (SOURCE_TOPICS, str(sd["id"]))).fetchone()
        if ev is None:
            st["no_event"] += 1
            continue
        try:
            blocks = extract(blob.get(sd["blob_key"]), sd["mime"], ev["payload"].get("file_name", ""))
        except Exception:
            st["unreadable"] += 1
            continue
        result = request_ocr(conn, sd, blocks, ev["topic"], ev["payload"])
        st[result] += 1
        conn.execute("UPDATE regulation.review_task SET detail = detail || %s::jsonb WHERE kind = 'LOW_TEXT'"
                     " AND target = %s", (json.dumps({"reason": low_text_reason(result), "ocr": result},
                                                     ensure_ascii=False), f"source:{sd['id']}"))
    if dry_run:
        conn.rollback()
    else:
        conn.commit()
    return st


def status(conn) -> dict:
    by = {r["s"]: r["n"] for r in conn.execute(
        "SELECT ocr_status AS s, count(*) AS n FROM regulation.source_document WHERE ocr_status IS NOT NULL"
        " GROUP BY 1 ORDER BY 1").fetchall()}
    q = conn.execute("SELECT count(*) FILTER (WHERE attempts < %s) AS queued, count(*) FILTER (WHERE attempts >= %s)"
                     " AS parked FROM ops.outbox WHERE topic = %s AND processed_at IS NULL",
                     (MAX_ATTEMPTS, MAX_ATTEMPTS, TOPIC)).fetchone()
    low = conn.execute("SELECT count(*) AS n FROM regulation.review_task WHERE kind = 'LOW_TEXT' AND status = 'OPEN'"
                       ).fetchone()["n"]
    return {"ocr_status": by, "queued": q["queued"], "parked": q["parked"], "open_low_text": low}
