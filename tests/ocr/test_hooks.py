from dataclasses import dataclass

from reg.core.extract.pdf import extract_pdf
from reg.platform.ocr_hooks import TOPIC, close_low_text, low_text_reason, needs_ocr, request_ocr
from tests.ocr.fx import BROKEN, SCAN, TEXT_PDF


@dataclass
class B:
    text: str
    page: int | None = 1


def test_needs_ocr_on_real_samples():
    assert needs_ocr(extract_pdf(BROKEN.read_bytes())) == "broken_digits"
    assert needs_ocr(extract_pdf(SCAN.read_bytes())) == "no_text"
    assert needs_ocr(extract_pdf(TEXT_PDF.read_bytes())) is None


def test_needs_ocr_rules():
    assert needs_ocr([]) == "no_text"  # 글자 층이 아예 없는 스캔본
    assert needs_ocr([B(". , 5 , 5 | 1. | 2. :", 1), B("23 ( ) | . , 30", 3)]) == "no_text"  # 문장부호만 남음
    body = "가나다라마바사아자차카타파하" * 3
    assert needs_ocr([B(f"제 조 (목적) {body}"), B("제 조 (정의)"), B("제 조 (범위)")]) == "broken_digits"
    # 번호 목차형 기준 문서: 글자 층은 멀쩡하고 제N조가 없다 → OCR해도 그대로
    assert needs_ocr([B(f"1. 목적 ○ 이 기준은 인사관리요령 제45조에 따라 {body}")]) is None
    assert needs_ocr([B(f"제 1 조 (목적) {body}"), B("제 2 조"), B("제 3 조")]) is None  # 띄어 쓴 정상 번호


def _sd(conn, sid):
    return conn.execute("SELECT * FROM regulation.source_document WHERE id = %s", (sid,)).fetchone()


def _ocr_events(conn):
    return conn.execute("SELECT payload FROM ops.outbox WHERE topic = %s", (TOPIC,)).fetchall()


def test_request_ocr_emits_once(conn, seeded):
    payload = {"seq": "186618", "source_document_id": seeded, "file_name": "방사선재해보상기준.pdf"}
    blocks = extract_pdf(BROKEN.read_bytes())
    assert request_ocr(conn, _sd(conn, seeded), blocks, "regulation.source_fetched", payload) == "pending"
    assert request_ocr(conn, _sd(conn, seeded), blocks, "regulation.source_fetched", payload) == "pending"
    ev = _ocr_events(conn)
    assert len(ev) == 1
    assert ev[0]["payload"] == {"source_document_id": seeded, "topic": "regulation.source_fetched",
                                "payload": payload, "reason": "broken_digits"}
    assert _sd(conn, seeded)["ocr_status"] == "pending"


def test_request_ocr_not_needed_and_non_pdf(conn, seeded):
    sd = dict(_sd(conn, seeded))
    assert request_ocr(conn, sd, [B("1. 목적 ○ " + "가나다" * 20)], "regulation.source_fetched", {}) == "not_needed"
    assert _sd(conn, seeded)["ocr_status"] == "not_needed" and _ocr_events(conn) == []
    hwp = {"id": seeded, "mime": "application/x-hwp", "ocr_status": None}
    assert request_ocr(conn, hwp, [], "regulation.source_fetched", {}) is None


def test_close_low_text_only_touches_open_source_task(conn, seeded):
    conn.execute("INSERT INTO regulation.review_task (kind, target) VALUES ('LOW_TEXT', %s), ('PARSE', %s)",
                 (f"source:{seeded}", f"source:{seeded}"))
    assert close_low_text(conn, seeded) == 1
    rows = {r["kind"]: r for r in conn.execute("SELECT kind, status, decision FROM regulation.review_task").fetchall()}
    assert rows["LOW_TEXT"]["status"] == "RESOLVED" and rows["LOW_TEXT"]["decision"] == {"auto": "reparsed"}
    assert rows["PARSE"]["status"] == "OPEN"
    assert close_low_text(conn, seeded) == 0


def test_low_text_reason_texts():
    assert "OCR 대기" in low_text_reason("pending")
    assert "조문 형식이 아님" in low_text_reason("not_needed")
    assert "OCR 후에도" in low_text_reason("ready")
    assert "OCR 실패" in low_text_reason("failed")
    assert "HWP" in low_text_reason(None)
