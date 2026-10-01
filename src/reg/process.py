"""outbox 소비자: 수집 이벤트 → 추출 → 파싱 → 시행일 판정 → 적재."""
import json
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
    if sd["mime"] in HWP_MIMES and sd["view_status"] == "ready" and sd["view_blob_key"]:
        locate(doc, extract_pdf(blob.get(sd["view_blob_key"])))  # 이미 만든 보기용 PDF 재사용 (재처리 시 변환 생략)
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


def rebuild_all(conn) -> int:
    conn.execute("TRUNCATE " + ", ".join(f"regulation.{t}" for t in STRUCTURE_TABLES) + " CASCADE")
    n = conn.execute("UPDATE regulation.outbox SET processed_at = NULL, attempts = 0, last_error = NULL"
                     " WHERE topic = ANY(%s)", (list(TOPICS),)).rowcount
    conn.commit()
    return n


def kst_today() -> date:
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def prepare_source_fetched(conn, blob: BlobStore, payload: dict, today: date,
                           converter: Converter | None = None) -> tuple:
    """ALIO 파일 하나: 추출·파싱·시행일·보기용 PDF·버전 추가까지. 계보 재계산은 묶음 끝에서 한 번."""
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
        # 다시 시도해도 같다(스캔본, 글꼴 숫자 인코딩 손상 등): 검수 큐로 보내고 처리 완료로 둔다
        conn.execute(
            "INSERT INTO regulation.review_task (kind, target, detail) VALUES ('LOW_TEXT', %s, %s)"
            " ON CONFLICT (kind, target) DO UPDATE SET detail = EXCLUDED.detail",
            (f"source:{sd['id']}", json.dumps({"reason": "조문 번호를 읽지 못함 (스캔본 또는 글꼴 숫자 인코딩 손상, OCR 필요)",
                                               "file_name": payload["file_name"], "seq": payload["seq"],
                                               "stats": doc.meta.get("stats")}, ensure_ascii=False)))
        return None
    alio_date = rule["revised_on"] if this and this["ord"] == last_ord else None
    eff = resolve(doc, alio_date=alio_date, filename=payload["file_name"])
    _view(conn, blob, sd, doc, converter)
    wid = work_key_for_regulation(conn, rule["inst_code"], rule["institution_id"], rule["title"], rule["seq"])
    upsert_work(conn, wid, "INTERNAL_REG", rule["title"], rule["institution_id"], {"alio_seq": rule["seq"]})
    vid = add_version(conn, wid, sd["id"], doc, eff, posted_on=rule["posted_on"])
    return wid, vid, doc, eff


def prepare_law_fetched(conn, blob: BlobStore, payload: dict, today: date, converter: Converter | None = None) -> tuple:
    sd = conn.execute("SELECT * FROM regulation.source_document WHERE id = %s",
                      (payload["source_document_id"],)).fetchone()
    doc = parse_law_xml(blob.get(sd["blob_key"]))
    wid = f"kr/law/{payload['law_id']}"
    upsert_work(conn, wid, doc.meta.get("kind") or "LAW", doc.title, None,
                {"law_id": payload["law_id"], "mst": payload["mst"]})
    eff = resolve(doc)
    return wid, add_version(conn, wid, sd["id"], doc, eff), doc, eff


HANDLERS = {"regulation.source_fetched": prepare_source_fetched, "regulation.law_fetched": prepare_law_fetched}
GROUP_FIELD = {"regulation.source_fetched": "seq", "regulation.law_fetched": "law_id"}


def _fail(conn, ev: dict, e: Exception, st: dict) -> None:
    conn.execute("UPDATE regulation.outbox SET attempts = attempts + 1, claimed_at = now(), last_error = %s"
                 " WHERE id = %s", (f"{type(e).__name__}: {e}"[:2000], ev["id"]))
    st["failed"] += 1
    if ev["attempts"] + 1 >= MAX_ATTEMPTS:
        st["parked"] += 1


def process_once(conn, blob: BlobStore, limit: int = 100, today: date | None = None,
                 converter: Converter | None = None) -> dict:
    """같은 규정의 대기 이벤트를 한 묶음으로 처리한다: 버전을 모두 더한 뒤 계보·참조·품질을 한 번만 계산.

    묶음마다 커밋하고, 규정 단위 advisory lock으로 여러 작업자가 동시에 돌아도 같은 규정은 한 작업자만 맡는다.
    """
    today = today or kst_today()
    st = {"claimed": 0, "ok": 0, "failed": 0, "parked": 0}
    q = ("SELECT id, topic, payload, attempts FROM regulation.outbox WHERE processed_at IS NULL AND attempts < %s"
         " AND topic = ANY(%s)")
    while st["claimed"] < limit:
        first = conn.execute(q + " ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED",
                             (MAX_ATTEMPTS, list(TOPICS))).fetchone()
        if first is None:
            break
        field = GROUP_FIELD[first["topic"]]
        key = first["payload"].get(field)
        group = [first] + (conn.execute(
            q + " AND topic = %s AND payload->>%s = %s AND id <> %s ORDER BY id FOR UPDATE SKIP LOCKED",
            (MAX_ATTEMPTS, list(TOPICS), first["topic"], field, key, first["id"])).fetchall() if key else [])
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{first['topic']}:{key}",))
        st["claimed"] += len(group)
        done = []
        for ev in group:
            try:
                with conn.transaction():
                    done.append((ev, HANDLERS[ev["topic"]](conn, blob, ev["payload"], today, converter)))
            except Exception as e:  # 파일 하나의 실패가 묶음을 멈추지 않게
                _fail(conn, ev, e, st)
        skipped = [ev for ev, r in done if r is None]
        done = [(ev, r) for ev, r in done if r is not None]
        for ev in skipped:
            conn.execute("UPDATE regulation.outbox SET processed_at = now(), claimed_at = now(), last_error = NULL"
                         " WHERE id = %s", (ev["id"],))
            st["ok"] += 1
        if done:
            try:
                with conn.transaction():
                    for wid in dict.fromkeys(r[0] for _, r in done):
                        rebuild_work(conn, wid, today)
                        resolve_and_store(conn, wid)
                        record_reference_tasks(conn, wid)
                    for ev, (wid, vid, doc, eff) in done:
                        record(conn, wid, vid, check(doc, eff))
                        conn.execute("UPDATE regulation.outbox SET processed_at = now(), claimed_at = now(),"
                                     " last_error = NULL WHERE id = %s", (ev["id"],))
                st["ok"] += len(done)
            except Exception as e:
                for ev, _ in done:
                    _fail(conn, ev, e, st)
        conn.commit()
    return st
