from reg.core.ingest.process import process_once
from reg.platform.ocr import OcrLine, dump_lines
from reg.platform.ocr_hooks import TOPIC
from tests.ocr.fx import TEXT_PDF, lines_of
from tests.test_process import TODAY


def _low_text(conn, sid):
    return conn.execute("SELECT status, detail FROM regulation.review_task WHERE kind = 'LOW_TEXT' AND target = %s",
                        (f"source:{sid}",)).fetchone()


def _sd(conn, sid):
    return conn.execute("SELECT * FROM regulation.source_document WHERE id = %s", (sid,)).fetchone()


def _reset_events(conn):
    conn.execute("UPDATE ops.outbox SET processed_at = NULL, attempts = 0 WHERE topic = 'regulation.source_fetched'")
    conn.commit()


def _n_ocr_events(conn) -> int:
    return conn.execute("SELECT count(*) AS n FROM ops.outbox WHERE topic = %s", (TOPIC,)).fetchone()["n"]


def _mark_ready(conn, blob, sid, lines):
    key = "ocr/test.lines.json"
    blob.put(key, dump_lines(lines), "application/json")
    conn.execute("UPDATE regulation.source_document SET ocr_status = 'ready', ocr_blob_key = %s WHERE id = %s",
                 (key, sid))
    _reset_events(conn)


def test_unreadable_pdf_requests_ocr_and_keeps_low_text(conn, blob, seeded):
    assert process_once(conn, blob, today=TODAY)["ok"] == 1
    t = _low_text(conn, seeded)
    assert t["status"] == "OPEN" and t["detail"]["ocr"] == "pending" and "OCR 대기" in t["detail"]["reason"]
    assert t["detail"]["file_name"] == "방사선재해보상기준.pdf"
    ev = conn.execute("SELECT payload FROM ops.outbox WHERE topic = %s", (TOPIC,)).fetchone()["payload"]
    assert ev["reason"] == "broken_digits" and ev["payload"]["seq"] == "186618"
    assert conn.execute("SELECT count(*) AS n FROM regulation.work_version").fetchone()["n"] == 0


def test_reparse_while_pending_does_not_request_again(conn, blob, seeded):
    process_once(conn, blob, today=TODAY)
    _reset_events(conn)
    process_once(conn, blob, today=TODAY)
    assert _n_ocr_events(conn) == 1


def test_not_needed_pdf_gets_reason_and_no_event(conn, blob, seeded, monkeypatch):
    import reg.platform.ocr_hooks as hooks

    monkeypatch.setattr(hooks, "needs_ocr", lambda blocks: None)  # 번호 목차형 기준 문서와 같은 판정
    process_once(conn, blob, today=TODAY)
    t = _low_text(conn, seeded)
    assert t["detail"]["ocr"] == "not_needed" and "조문 형식이 아님" in t["detail"]["reason"]
    assert _sd(conn, seeded)["ocr_status"] == "not_needed" and _n_ocr_events(conn) == 0


def test_ocr_ready_source_parses_from_ocr_lines_and_closes_low_text(conn, blob, seeded):
    process_once(conn, blob, today=TODAY)
    _mark_ready(conn, blob, seeded, lines_of(TEXT_PDF))
    assert process_once(conn, blob, today=TODAY)["ok"] == 1
    assert conn.execute("SELECT count(*) AS n FROM regulation.work_version").fetchone()["n"] == 1
    assert _low_text(conn, seeded)["status"] == "RESOLVED"
    sd = _sd(conn, seeded)
    assert sd["view_blob_key"] == sd["blob_key"]  # 보기 화면은 원본 PDF, 좌표는 원본 쪽 기준 (R4)


def test_ocr_ready_but_still_unreadable_says_so(conn, blob, seeded):
    process_once(conn, blob, today=TODAY)
    _mark_ready(conn, blob, seeded, [OcrLine("1. 목적 ○ 이 기준은 …", 1, None)])  # OCR이 조문을 못 찾은 경우
    process_once(conn, blob, today=TODAY)
    t = _low_text(conn, seeded)
    assert t["status"] == "OPEN" and t["detail"]["ocr"] == "ready" and "OCR 후에도" in t["detail"]["reason"]
    assert _n_ocr_events(conn) == 1
