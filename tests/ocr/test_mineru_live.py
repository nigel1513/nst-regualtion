"""실서버 MinerU 스모크. REG_MINERU_URL(필요하면 REG_MINERU_API_KEY)을 환경변수로 줄 때만 돈다.

  REG_MINERU_URL=http://192.168.0.2:8004 REG_MINERU_API_KEY=... uv run pytest tests/ocr/test_mineru_live.py -m mineru_live
"""
import os
import re

import pytest

from reg.core.model import Block
from reg.core.parse import parse_blocks
from reg.platform.mineru import MineruClient
from reg.platform.ocr import MineruOcr
from tests.ocr.fx import BROKEN, SCAN

pytestmark = [pytest.mark.mineru_live,
              pytest.mark.skipif(not os.environ.get("REG_MINERU_URL"), reason="REG_MINERU_URL 없음")]


def _engine() -> MineruOcr:
    return MineruOcr(MineruClient(os.environ["REG_MINERU_URL"], os.environ.get("REG_MINERU_API_KEY", ""),
                                  poll_interval=2, max_wait=900))


def _articles(res) -> list[str]:
    doc = parse_blocks([Block(ln.text, ln.page, ln.bbox) for ln in res.lines])
    return [p.path for p in doc.provisions if p.unit == "article"]


def test_health_offers_middle_json_and_markdown():
    assert _engine().available() is True


def test_broken_digit_pdf_reads_article_numbers_at_the_right_place():
    res = _engine().ocr(BROKEN.read_bytes())
    first = next(ln for ln in res.lines if re.match(r"제\s*1\s*조", ln.text))
    assert first.page == 3  # 1쪽 표지·목차, 2쪽 빈 쪽, 3쪽 본문 (원본 PDF 기준)
    assert first.bbox is not None and first.bbox[1] < 842 * 0.4  # 왼쪽 위 원점: 본문 첫 조는 쪽 위쪽 (R4 확인)
    arts = _articles(res)
    assert {"a1", "a2", "a3", "a8"} <= set(arts) and len(arts) >= 8  # Tesseract 예비 기준 9/9


def test_scanned_pdf_reads_articles():
    res = _engine().ocr(SCAN.read_bytes())
    assert "퇴직금" in res.markdown
    assert len(_articles(res)) >= 10  # Tesseract 예비 기준 15
