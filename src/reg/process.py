"""outbox 소비자: 수집 이벤트 → 추출 → 파싱 → 시행일 판정 → 적재."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from reg.extract import extract
from reg.extract.pdf import extract_pdf
from reg.quality import check, record, record_reference_tasks
from reg.refs import resolve_and_store
from reg.load.loader import add_version, rebuild_work, upsert_work, work_key_for_regulation
from reg.storage.blob import BlobStore
from reg.structure.effective import resolve
from reg.structure.law_xml import parse_law_xml
from reg.structure.parse import parse_blocks
from reg.views.anchor import locate
from reg.views.converter import ConversionError, Converter

MAX_ATTEMPTS = 3
TOPICS = ("regulation.source_fetched", "regulation.law_fetched")
HWP_MIMES = {"application/x-hwp": "hwp", "application/hwp+zip": "hwpx"}
STRUCTURE_TABLES = ["reference", "review_task", "provision_change", "version_provision", "provision_version",
                    "provision", "amendment_history", "work_version", "work"]


def _view(conn, blob, sd, doc, converter) -> None:
    if sd["mime"] == "application/pdf":
        conn.execute("UPDATE regulation.source_document SET view_blob_key = blob_key, view_status = 'not_needed'"
                     " WHERE id = %s", (sd["id"],))
        return
    if converter is None or sd["mime"] not in HWP_MIMES:
        return
    try:
        pdf = converter.to_pdf(blob.get(sd["blob_key"]), HWP_MIMES[sd["mime"]])
    except ConversionError:
        conn.execute("UPDATE regulation.source_document SET view_status = 'failed' WHERE id = %s", (sd["id"],))
        return
    key = f"view/{sd['sha256']}.pdf"
    if not blob.exists(key):
        blob.put(key, pdf, "application/pdf")
    conn.execute("UPDATE regulation.source_document SET view_blob_key = %s, view_status = 'ready' WHERE id = %s",
                 (key, sd["id"]))
    locate(doc, extract_pdf(pdf))


def _after_load(conn, wid: str, vid: str, doc, eff) -> None:
    resolve_and_store(conn, wid)
    record_reference_tasks(conn, wid)
    record(conn, wid, vid, check(doc, eff))


def rebuild_all(conn) -> int:
    conn.execute("TRUNCATE " + ", ".join(f"regulation.{t}" for t in STRUCTURE_TABLES) + " CASCADE")
    n = conn.execute("UPDATE regulation.outbox SET processed_at = NULL, attempts = 0, last_error = NULL"
                     " WHERE topic = ANY(%s)", (list(TOPICS),)).rowcount
    conn.commit()
    return n


def kst_today() -> date:
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def handle_source_fetched(conn, blob: BlobStore, payload: dict, today: date, converter: Converter | None = None) -> str:
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
    _view(conn, blob, sd, doc, converter)
    wid = work_key_for_regulation(conn, rule["inst_code"], rule["institution_id"], rule["title"], rule["seq"])
    upsert_work(conn, wid, "INTERNAL_REG", rule["title"], rule["institution_id"], {"alio_seq": rule["seq"]})
    vid = add_version(conn, wid, sd["id"], doc, eff, posted_on=rule["posted_on"])
    rebuild_work(conn, wid, today)
    _after_load(conn, wid, vid, doc, eff)
    return wid


def handle_law_fetched(conn, blob: BlobStore, payload: dict, today: date, converter: Converter | None = None) -> str:
    sd = conn.execute("SELECT * FROM regulation.source_document WHERE id = %s",
                      (payload["source_document_id"],)).fetchone()
    doc = parse_law_xml(blob.get(sd["blob_key"]))
    wid = f"kr/law/{payload['law_id']}"
    upsert_work(conn, wid, doc.meta.get("kind") or "LAW", doc.title, None,
                {"law_id": payload["law_id"], "mst": payload["mst"]})
    eff = resolve(doc)
    vid = add_version(conn, wid, sd["id"], doc, eff)
    rebuild_work(conn, wid, today)
    _after_load(conn, wid, vid, doc, eff)
    return wid


HANDLERS = {"regulation.source_fetched": handle_source_fetched, "regulation.law_fetched": handle_law_fetched}


def process_once(conn, blob: BlobStore, limit: int = 100, today: date | None = None,
                 converter: Converter | None = None) -> dict:
    today = today or kst_today()
    st = {"claimed": 0, "ok": 0, "failed": 0, "parked": 0}
    events = conn.execute(
        "SELECT id, topic, payload, attempts FROM regulation.outbox WHERE processed_at IS NULL AND attempts < %s"
        " AND topic = ANY(%s) ORDER BY id LIMIT %s FOR UPDATE SKIP LOCKED",
        (MAX_ATTEMPTS, list(TOPICS), limit)).fetchall()
    for ev in events:  # 이벤트마다 커밋: 긴 변환이 배치 전체의 잠금을 잡지 않고, 중단돼도 끝난 이벤트는 남는다
        st["claimed"] += 1
        try:
            with conn.transaction():
                HANDLERS[ev["topic"]](conn, blob, ev["payload"], today, converter)
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
    conn.commit()
    return st
