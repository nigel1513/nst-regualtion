# src/reg/platform/ocr_hooks.py
"""출처 처리기와 OCR 모듈의 연결부: OCR 필요 판정, 요청(outbox), LOW_TEXT 닫기·사유.

출처 모듈은 reg.ocr을 import할 수 없으므로(overview §2.2) 처리기가 부르는 부분을 platform에 둔다.
blocks는 .text·.page를 가진 객체(core의 Block)다. platform은 core를 import하지 않는다.
"""
import json
import re
from collections.abc import Iterable

from reg.platform import outbox

TOPIC = "ocr.needed.v1"
MIN_HANGUL_PER_PAGE = 30
MIN_BLANK_ARTICLES = 3
_HANGUL = re.compile(r"[가-힣]")
_BLANK_ARTICLE = re.compile(r"제\s+조")  # 글꼴 숫자 인코딩이 깨져 '제 1 조'의 숫자만 빠진 모양
_REASONS = {
    None: "조문 번호를 읽지 못함 (HWP: 원문에 조문 형식이 없거나 추출 실패)",
    "pending": "조문 번호를 읽지 못함: 스캔본 또는 글꼴 숫자 인코딩 손상, OCR 대기",
    "ready": "OCR 후에도 조문 번호를 읽지 못함",
    "failed": "조문 번호를 읽지 못함: OCR 실패",
    "not_needed": "제N조 조문 형식이 아님: 번호 목차형 기준 등, OCR로 나아지지 않음",
}


def needs_ocr(blocks: Iterable) -> str | None:
    blocks = list(blocks)
    text = "\n".join(b.text for b in blocks)
    pages = max((b.page or 1 for b in blocks), default=1)
    if len(_HANGUL.findall(text)) < MIN_HANGUL_PER_PAGE * pages:
        return "no_text"
    if len(_BLANK_ARTICLE.findall(text)) >= MIN_BLANK_ARTICLES:
        return "broken_digits"
    return None


def request_ocr(conn, sd: dict, blocks: Iterable, topic: str, payload: dict) -> str | None:
    """조문을 못 읽은 원본 하나. OCR이 도움이 되는 PDF면 ocr.needed.v1을 남기고 'pending'을 돌려준다.

    도움이 안 되는 PDF는 'not_needed'다. 이미 상태가 있으면(대기·완료·실패·불필요) 아무것도 쓰지 않고 그 상태를
    돌려준다. 같은 원본을 여러 번 다시 파싱해도 요청은 한 번이다. PDF가 아니면 None이다.
    """
    if sd["mime"] != "application/pdf":
        return None
    if sd["ocr_status"] is not None:
        return sd["ocr_status"]
    kind = needs_ocr(blocks)
    status = "pending" if kind else "not_needed"
    won = conn.execute("UPDATE regulation.source_document SET ocr_status = %s WHERE id = %s AND ocr_status IS NULL"
                       " RETURNING id", (status, sd["id"])).fetchone()
    if won is None:  # 다른 작업자가 먼저 정했다
        return conn.execute("SELECT ocr_status FROM regulation.source_document WHERE id = %s",
                            (sd["id"],)).fetchone()["ocr_status"]
    if kind:
        outbox.write(conn, TOPIC, {"source_document_id": sd["id"], "topic": topic, "payload": payload, "reason": kind})
    return status


def close_low_text(conn, source_document_id: int) -> int:
    return conn.execute("UPDATE regulation.review_task SET status = 'RESOLVED', resolved_at = now(), decision = %s"
                        " WHERE kind = 'LOW_TEXT' AND target = %s AND status = 'OPEN'",
                        (json.dumps({"auto": "reparsed"}), f"source:{source_document_id}")).rowcount


def low_text_reason(ocr_status: str | None) -> str:
    return _REASONS[ocr_status]
