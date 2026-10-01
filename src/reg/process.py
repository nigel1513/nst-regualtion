"""outbox 소비자: 수집 이벤트 → 추출 → 파싱 → 시행일 판정 → 적재."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from reg.extract import extract
from reg.load.loader import add_version, rebuild_work, upsert_work, work_key_for_regulation
from reg.storage.blob import BlobStore
from reg.structure.effective import resolve
from reg.structure.law_xml import parse_law_xml
from reg.structure.parse import parse_blocks

MAX_ATTEMPTS = 3
TOPICS = ("regulation.source_fetched", "regulation.law_fetched")


def kst_today() -> date:
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def handle_source_fetched(conn, blob: BlobStore, payload: dict, today: date) -> str:
    sd = conn.execute("SELECT * FROM regulation.source_document WHERE id = %s",
                      (payload["source_document_id"],)).fetchone()
    rule = conn.execute(
        "SELECT r.*, i.code AS inst_code FROM regulation.alio_rule r JOIN regulation.institution i"
        " ON i.id = r.institution_id WHERE r.seq = %s", (payload["seq"],)).fetchone()
    last_ord = conn.execute("SELECT max(ord) AS m FROM regulation.alio_rule_file WHERE seq = %s AND status='fetched'",
                            (payload["seq"],)).fetchone()["m"]
    this = conn.execute("SELECT ord FROM regulation.alio_rule_file WHERE file_no = %s",
                        (payload["file_no"],)).fetchone()
    doc = parse_blocks(extract(blob.get(sd["blob_key"]), sd["mime"], payload["file_name"]))
    if not any(p.unit == "article" for p in doc.provisions):
        raise ValueError(f"조문을 찾지 못함 (stats={doc.meta.get('stats')})")
    alio_date = rule["revised_on"] if this and this["ord"] == last_ord else None
    eff = resolve(doc, alio_date=alio_date, filename=payload["file_name"])
    wid = work_key_for_regulation(conn, rule["inst_code"], rule["institution_id"], rule["title"], rule["seq"])
    upsert_work(conn, wid, "INTERNAL_REG", rule["title"], rule["institution_id"], {"alio_seq": rule["seq"]})
    add_version(conn, wid, sd["id"], doc, eff, posted_on=rule["posted_on"])
    rebuild_work(conn, wid, today)
    return wid


def handle_law_fetched(conn, blob: BlobStore, payload: dict, today: date) -> str:
    sd = conn.execute("SELECT * FROM regulation.source_document WHERE id = %s",
                      (payload["source_document_id"],)).fetchone()
    doc = parse_law_xml(blob.get(sd["blob_key"]))
    wid = f"kr/law/{payload['law_id']}"
    upsert_work(conn, wid, doc.meta.get("kind") or "LAW", doc.title, None,
                {"law_id": payload["law_id"], "mst": payload["mst"]})
    add_version(conn, wid, sd["id"], doc, resolve(doc))
    rebuild_work(conn, wid, today)
    return wid


HANDLERS = {"regulation.source_fetched": handle_source_fetched, "regulation.law_fetched": handle_law_fetched}


def process_once(conn, blob: BlobStore, limit: int = 100, today: date | None = None) -> dict:
    today = today or kst_today()
    st = {"claimed": 0, "ok": 0, "failed": 0, "parked": 0}
    events = conn.execute(
        "SELECT id, topic, payload, attempts FROM regulation.outbox WHERE processed_at IS NULL AND attempts < %s"
        " AND topic = ANY(%s) ORDER BY id LIMIT %s FOR UPDATE SKIP LOCKED",
        (MAX_ATTEMPTS, list(TOPICS), limit)).fetchall()
    for ev in events:
        st["claimed"] += 1
        try:
            with conn.transaction():
                HANDLERS[ev["topic"]](conn, blob, ev["payload"], today)
                conn.execute("UPDATE regulation.outbox SET processed_at = now(), claimed_at = now(),"
                             " last_error = NULL WHERE id = %s", (ev["id"],))
            st["ok"] += 1
        except Exception as e:  # 이벤트 하나의 실패가 배치를 멈추지 않게
            conn.execute("UPDATE regulation.outbox SET attempts = attempts + 1, claimed_at = now(), last_error = %s"
                         " WHERE id = %s", (f"{type(e).__name__}: {e}"[:2000], ev["id"]))
            st["failed"] += 1
            if ev["attempts"] + 1 >= MAX_ATTEMPTS:
                st["parked"] += 1
    conn.commit()
    return st
