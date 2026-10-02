# src/reg/core/extract/pdf.py
"""텍스트 PDF 줄 추출. 두 쪽 모아찍기 가르기, 반복 머리글·꼬리글·쪽번호 제거, 줄마다 쪽·bbox 보존."""
import io
from collections import Counter

import pdfplumber

from reg.core.extract.layout import is_page_number_line, is_structural, running_key, two_up_gutter
from reg.core.model import Block
from reg.core.text import clean

EDGE_BAND = 0.08  # 쪽 위·아래 이 비율 안의 줄도 머리글·꼬리글 후보 (각 단위의 처음·끝 두 줄과 함께)


def _units(page):
    """한 쪽을 읽기 단위로 나눈다: 두 쪽 모아찍기면 왼쪽·오른쪽 반쪽, 아니면 쪽 전체."""
    words = page.extract_words()
    mid = two_up_gutter([(w["x0"], w["x1"]) for w in words], page.width, page.height)
    if mid is None:
        return [page]
    return [page.crop((0, 0, mid, page.height)), page.crop((mid, 0, page.width, page.height))]


def extract_pdf(data: bytes) -> list[Block]:
    units: list[list[tuple[Block, bool]]] = []  # 읽기 단위마다 (줄, 가장자리 줄인가)
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for no, page in enumerate(pdf.pages, 1):
            h = page.height
            for part in _units(page):
                lines = []
                for ln in part.extract_text_lines(strip=True):
                    t = clean(ln["text"])
                    if t:
                        lines.append(Block(t, no, (round(ln["x0"], 1), round(ln["top"], 1),
                                                   round(ln["x1"], 1), round(ln["bottom"], 1))))
                edge = [i < 2 or i >= len(lines) - 2 or b.bbox[1] < h * EDGE_BAND or b.bbox[3] > h * (1 - EDGE_BAND)
                        for i, b in enumerate(lines)]
                units.append(list(zip(lines, edge, strict=True)))
    return drop_running(units)


def drop_running(units: list[list[tuple[Block, bool]]]) -> list[Block]:
    """머리글·꼬리글: 여러 단위의 가장자리에 (숫자를 무시하면) 같은 텍스트로 반복되는 줄과 쪽번호 줄을 뺀다.

    별표·부칙·조 머리 같은 구조 줄은 반복돼도 빼지 않는다 ('별지 제1호 서식', '별지 제2호 서식' …)."""
    seen = Counter()
    for lines in units:
        seen.update({running_key(b.text) for b, e in lines if e and not is_structural(b.text)})
    running = {k for k, n in seen.items() if n >= 3 and n >= len(units) * 0.3}
    out = []
    for lines in units:
        for b, e in lines:
            if e and not is_structural(b.text) and (running_key(b.text) in running or is_page_number_line(b.text)):
                continue
            out.append(b)
    return out
