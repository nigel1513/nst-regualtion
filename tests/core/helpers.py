# tests/core/helpers.py
"""M6-6 테스트 도우미: 실제 PDF 조각으로 판본 하나를 적재한다 (처리기 없이 core 함수만)."""
from datetime import date
from pathlib import Path

from reg.core.effective import Effective
from reg.core.extract.pdf import extract_pdf
from reg.core.ingest.loader import add_version, rebuild_work, upsert_work
from reg.core.model import Block
from reg.core.parse import parse_blocks
from reg.platform.archive import store
from reg.platform.sniff import FileKind

FX = Path(__file__).parent / "fixtures"
PDF = FX / "pdf"


def load_pdf_version(conn, blob, name: str, wid: str = "kr/reg/KASI/내자구매요령", title: str = "내자구매요령",
                     lead: str | None = "제1조(목적) 이 요령은 내자구매에 필요한 사항을 정한다.") -> tuple[str, str]:
    """fixtures/pdf/{name}을 원본·보기용 PDF로 두고 판본을 적재한다. 조각에 조문이 없으면 lead 줄을 앞에 붙인다."""
    data = (PDF / name).read_bytes()
    doc = store(conn, blob, source="alio", url="u", content=data, kind=FileKind("application/pdf", "pdf"), meta={})
    conn.execute("UPDATE regulation.source_document SET view_blob_key = blob_key, view_status = 'not_needed'"
                 " WHERE id = %s", (doc.id,))
    blocks = ([Block(lead, 1, (82.2, 60.0, 400.0, 70.0))] if lead else []) + extract_pdf(data)
    upsert_work(conn, wid, "INTERNAL_REG", title, None, {})
    vid = add_version(conn, wid, doc.id, parse_blocks(blocks),
                      Effective(date(2023, 12, 29), "supplement", "CONFIRMED", None))
    rebuild_work(conn, wid, date(2026, 10, 2))
    conn.commit()
    return vid, doc.sha256
