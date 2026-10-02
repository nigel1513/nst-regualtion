import json

from reg.core.ingest.process import process_once
from reg.ocr.service import enqueue_low_text, md_key, ocr_key, raw_key, requeue, run_pending, status
from reg.platform.ocr_hooks import TOPIC
from tests.ocr.fx import TEXT_PDF, FakeOcr, lines_of
from tests.test_process import TODAY

ZERO = {"claimed": 0, "ready": 0, "retry": 0, "failed": 0, "skipped": 0, "requeued": 0, "processed": 0,
        "unavailable": False}


def _sd(conn, sid):
    return conn.execute("SELECT * FROM regulation.source_document WHERE id = %s", (sid,)).fetchone()


def _low_text(conn, sid):
    return conn.execute("SELECT status, detail FROM regulation.review_task WHERE kind = 'LOW_TEXT' AND target = %s",
                        (f"source:{sid}",)).fetchone()


def _ocr_event(conn):
    return conn.execute("SELECT * FROM ops.outbox WHERE topic = %s", (TOPIC,)).fetchone()


def test_full_loop_unreadable_pdf_becomes_a_version(conn, blob, seeded):
    process_once(conn, blob, today=TODAY)  # 조문 못 읽음 → LOW_TEXT + ocr.needed.v1
    eng = FakeOcr(lines_of(TEXT_PDF))
    st = run_pending(conn, blob, eng)
    assert st == {**ZERO, "claimed": 1, "ready": 1, "requeued": 1, "processed": 1}
    sd = _sd(conn, seeded)
    assert (sd["ocr_status"], sd["ocr_blob_key"], sd["ocr_engine"]) == ("ready", ocr_key(sd["sha256"]), "fake-1")
    assert blob.exists(raw_key(sd["sha256"])) and blob.exists(md_key(sd["sha256"]))
    orig = conn.execute("SELECT processed_at, attempts FROM ops.outbox WHERE topic = 'regulation.source_fetched'"
                        ).fetchone()
    assert orig["processed_at"] is None and orig["attempts"] == 0
    assert _ocr_event(conn)["processed_at"] is not None

    assert process_once(conn, blob, today=TODAY)["ok"] == 1  # OCR 줄로 다시 파싱
    v = conn.execute("SELECT * FROM regulation.work_version").fetchone()
    assert v["source_document_id"] == seeded
    assert _low_text(conn, seeded)["status"] == "RESOLVED"
    assert run_pending(conn, blob, eng)["claimed"] == 0 and eng.calls == 1


def test_gpu_down_before_start_touches_nothing(conn, blob, seeded):
    process_once(conn, blob, today=TODAY)
    eng = FakeOcr(lines_of(TEXT_PDF), healthy=False)
    assert run_pending(conn, blob, eng) == {**ZERO, "unavailable": True}
    ev = _ocr_event(conn)
    assert eng.calls == 0 and ev["attempts"] == 0 and ev["processed_at"] is None and ev["claimed_at"] is None


def test_service_lost_mid_job_does_not_count_an_attempt(conn, blob, seeded):
    process_once(conn, blob, today=TODAY)
    assert run_pending(conn, blob, FakeOcr(unavailable=True)) == {**ZERO, "claimed": 1, "unavailable": True}
    ev, sd = _ocr_event(conn), _sd(conn, seeded)
    assert ev["attempts"] == 0 and ev["processed_at"] is None and sd["ocr_status"] == "pending"
    assert run_pending(conn, blob, FakeOcr(lines_of(TEXT_PDF)))["ready"] == 1  # 다시 켜지면 그대로 처리


def test_nothing_queued_skips_health_check(conn, blob):
    eng = FakeOcr(healthy=False)
    assert run_pending(conn, blob, eng) == ZERO  # 대기 없음: 꺼져 있어도 unavailable이 아니다


def test_failure_once_per_run_then_parked_with_note(conn, blob, seeded):
    process_once(conn, blob, today=TODAY)
    eng = FakeOcr(fail=99)
    assert run_pending(conn, blob, eng) == {**ZERO, "claimed": 1, "retry": 1}
    assert eng.calls == 1 and _sd(conn, seeded)["ocr_status"] == "pending"
    assert run_pending(conn, blob, eng)["failed"] == 1
    sd, ev, t = _sd(conn, seeded), _ocr_event(conn), _low_text(conn, seeded)
    assert sd["ocr_status"] == "failed" and sd["ocr_engine"] == "fake"
    assert ev["attempts"] == 2 and ev["processed_at"] is None and "가짜 실패" in ev["last_error"]
    assert t["detail"]["ocr"]["status"] == "failed" and "가짜 실패" in t["detail"]["ocr"]["error"]
    assert t["detail"]["file_name"] == "방사선재해보상기준.pdf"  # 기존 정보는 합쳐서 남긴다
    assert run_pending(conn, blob, eng)["claimed"] == 0 and eng.calls == 2


def test_already_ready_is_requeued_without_running_ocr(conn, blob, seeded):
    process_once(conn, blob, today=TODAY)
    conn.execute("UPDATE regulation.source_document SET ocr_status = 'ready', ocr_blob_key = 'ocr/x.lines.json'"
                 " WHERE id = %s", (seeded,))
    conn.commit()
    eng = FakeOcr()
    st = run_pending(conn, blob, eng)
    assert st["skipped"] == 1 and st["requeued"] == 1 and st["processed"] == 1 and eng.calls == 0


def test_requeue_writes_new_event_when_original_is_gone(conn, seeded):
    conn.execute("DELETE FROM ops.outbox")
    payload = {"source_document_id": seeded, "seq": "186618", "file_name": "a.pdf"}
    assert requeue(conn, "regulation.source_fetched", payload) == 1
    row = conn.execute("SELECT payload, processed_at FROM ops.outbox").fetchone()
    assert row["payload"] == payload and row["processed_at"] is None


def _legacy_low_text(conn, sid):
    """M6-5 이전 처리기가 남긴 상태: 원래 이벤트는 처리 완료, LOW_TEXT만 열려 있고 ocr_status는 NULL."""
    conn.execute("UPDATE ops.outbox SET processed_at = now()")
    conn.execute("INSERT INTO regulation.review_task (kind, target, detail) VALUES ('LOW_TEXT', %s, %s)",
                 (f"source:{sid}", json.dumps({"reason": "옛 사유", "file_name": "방사선재해보상기준.pdf"})))
    conn.execute("INSERT INTO regulation.review_task (kind, target, detail) VALUES ('LOW_TEXT', 'kr/reg/X@2020-01-01',"
                 " '{\"articles\": 3}')")
    conn.commit()


def test_backfill_enqueues_open_low_text_pdfs(conn, blob, seeded):
    _legacy_low_text(conn, seeded)
    expect = {"pending": 1, "not_needed": 0, "no_event": 0, "unreadable": 0, "non_pdf": 0, "version_level": 1}
    assert enqueue_low_text(conn, blob, dry_run=True) == expect
    assert _ocr_event(conn) is None and _sd(conn, seeded)["ocr_status"] is None  # 시험 실행은 아무것도 쓰지 않는다
    assert enqueue_low_text(conn, blob) == expect
    assert _ocr_event(conn)["payload"]["payload"]["seq"] == "186618"
    t = _low_text(conn, seeded)
    assert t["detail"]["ocr"] == "pending" and t["detail"]["file_name"] == "방사선재해보상기준.pdf"
    assert enqueue_low_text(conn, blob)["pending"] == 0  # 두 번 돌려도 한 번만

    run_pending(conn, blob, FakeOcr(lines_of(TEXT_PDF)))
    assert process_once(conn, blob, today=TODAY)["ok"] == 1
    assert _low_text(conn, seeded)["status"] == "RESOLVED"


def test_status_counts(conn, blob, seeded):
    process_once(conn, blob, today=TODAY)
    assert status(conn) == {"ocr_status": {"pending": 1}, "queued": 1, "parked": 0, "open_low_text": 1}


class _Boom(FakeOcr):
    def ocr(self, pdf):
        self.calls += 1
        raise RuntimeError("예상 못한 오류")


def test_unexpected_error_counts_an_attempt_instead_of_stalling(conn, blob, seeded):
    """리뷰 Important #1: OcrError·OcrUnavailable 밖의 예외도 시도 1회로 센다. 대기열 맨 앞에서 영원히 막히지 않는다."""
    process_once(conn, blob, today=TODAY)
    eng = _Boom()
    assert run_pending(conn, blob, eng)["retry"] == 1
    ev = _ocr_event(conn)
    assert ev["attempts"] == 1 and "예상 못한 오류" in ev["last_error"]
    assert run_pending(conn, blob, eng)["failed"] == 1 and _sd(conn, seeded)["ocr_status"] == "failed"


def test_repeated_loss_while_healthy_turns_into_an_attempt(conn, blob, seeded):
    """리뷰 Important #1: 상태 확인은 정상인데 이 문서에서만 서비스가 거듭 사라지면(문서가 MinerU를 죽이는 경우)
    UNAVAILABLE_STRIKES번째에 시도 1회로 센다. 한 번의 소실은 여전히 세지 않는다."""
    from reg.ocr.service import UNAVAILABLE_STRIKES

    process_once(conn, blob, today=TODAY)
    eng = FakeOcr(unavailable=True)
    for _ in range(UNAVAILABLE_STRIKES - 1):
        assert run_pending(conn, blob, eng)["unavailable"] is True
        assert _ocr_event(conn)["attempts"] == 0
    st = run_pending(conn, blob, eng)
    ev = _ocr_event(conn)
    assert st["retry"] == 1 and st["unavailable"] is False
    assert ev["attempts"] == 1 and ev["payload"]["unavailable_strikes"] == 0 and "사라짐" in ev["last_error"]
    for _ in range(UNAVAILABLE_STRIKES):
        st = run_pending(conn, blob, eng)
    assert st["failed"] == 1 and _sd(conn, seeded)["ocr_status"] == "failed"


def test_tried_list_spans_calls_so_one_invocation_tries_once(conn, blob, seeded):
    """리뷰 Important #2: reg ocr run --all이 같은 이벤트를 연달아 두 번 시도하지 않는다."""
    process_once(conn, blob, today=TODAY)
    eng, tried = FakeOcr(fail=99), []
    assert run_pending(conn, blob, eng, tried=tried)["retry"] == 1
    assert run_pending(conn, blob, eng, tried=tried)["claimed"] == 0 and eng.calls == 1


def test_failed_ocr_updates_the_low_text_reason(conn, blob, seeded):
    """리뷰 Important #3: 실패로 굳으면 검수 사유도 'OCR 대기'가 아니라 'OCR 실패'다."""
    process_once(conn, blob, today=TODAY)
    eng = FakeOcr(fail=99)
    run_pending(conn, blob, eng)
    run_pending(conn, blob, eng)
    t = _low_text(conn, seeded)
    assert "OCR 실패" in t["detail"]["reason"] and t["detail"]["seq"] == "186618"
