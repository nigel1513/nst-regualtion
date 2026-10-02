"""ALIO 내부규정 파일 하나 → PreparedVersion (추출·파싱·시행일·보기용 PDF). 적재는 core가 한다."""
import json
from datetime import date

from reg.core.anchor import locate
from reg.core.effective import resolve
from reg.core.extract import extract
from reg.core.extract.pdf import extract_pdf
from reg.core.ingest.contract import PreparedVersion, SourceHandler
from reg.core.ingest.loader import work_key_for_regulation
from reg.core.model import Block
from reg.core.parse import parse_blocks
from reg.platform.convert import ConversionError, Converter
from reg.platform.ocr import load_lines
from reg.platform.ocr_hooks import close_low_text, low_text_reason, request_ocr
from reg.platform.storage.blob import BlobStore

HWP_MIMES = {"application/x-hwp": "hwp", "application/hwp+zip": "hwpx"}


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


def prepare(conn, blob: BlobStore, payload: dict, today: date, converter: Converter | None = None) -> PreparedVersion | None:
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
    if sd["ocr_blob_key"]:  # OCR 결과 줄(쪽·원본 PDF 좌표)로 파싱한다 (M6-5)
        blocks = [Block(ln.text, ln.page, ln.bbox) for ln in load_lines(blob.get(sd["ocr_blob_key"]))]
    else:
        blocks = extract(blob.get(sd["blob_key"]), sd["mime"], payload["file_name"])
    doc = parse_blocks(blocks)
    if not any(p.unit == "article" for p in doc.provisions):
        # 다시 시도해도 같다: 검수 큐에 남기고 처리 완료로 둔다. OCR로 나아질 PDF면 ocr.needed.v1을 남긴다 (M6-5)
        ocr = request_ocr(conn, sd, blocks, "regulation.source_fetched", payload)
        conn.execute(
            "INSERT INTO regulation.review_task (kind, target, detail) VALUES ('LOW_TEXT', %s, %s)"
            " ON CONFLICT (kind, target) DO UPDATE SET detail = EXCLUDED.detail",
            (f"source:{sd['id']}", json.dumps({"reason": low_text_reason(ocr), "ocr": ocr,
                                               "file_name": payload["file_name"], "seq": payload["seq"],
                                               "stats": doc.meta.get("stats")}, ensure_ascii=False)))
        return None
    close_low_text(conn, sd["id"])
    alio_date = rule["revised_on"] if this and this["ord"] == last_ord else None
    eff = resolve(doc, alio_date=alio_date, filename=payload["file_name"])
    _view(conn, blob, sd, doc, converter)
    wid = work_key_for_regulation(conn, rule["inst_code"], rule["institution_id"], rule["title"], rule["seq"])
    return PreparedVersion(wid, "INTERNAL_REG", rule["title"], rule["institution_id"], sd["id"], doc, eff,
                           {"alio_seq": rule["seq"]}, rule["posted_on"])


HANDLER = SourceHandler("regulation.source_fetched", "seq", prepare)
