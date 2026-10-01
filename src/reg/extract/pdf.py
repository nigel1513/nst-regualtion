"""텍스트 PDF 줄 추출. 반복 머리글·꼬리글·쪽번호 제거, 줄마다 쪽·bbox 보존."""
import io
import re
from collections import Counter

import pdfplumber

from reg.structure.model import Block
from reg.structure.text import clean

PAGE_NO = re.compile(r"^[-–]\s*\d+\s*[-–]$|^\d+\s*/\s*\d+$")


def extract_pdf(data: bytes) -> list[Block]:
    pages: list[list[Block]] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for no, page in enumerate(pdf.pages, 1):
            lines = []
            for ln in page.extract_text_lines(strip=True):
                t = clean(ln["text"])
                if t:
                    lines.append(Block(t, no, (round(ln["x0"], 1), round(ln["top"], 1),
                                               round(ln["x1"], 1), round(ln["bottom"], 1))))
            pages.append(lines)
    # 머리글·꼬리글: 여러 쪽의 첫 줄·끝 줄에 반복되는 같은 텍스트
    edge = Counter()
    for lines in pages:
        for b in lines[:2] + lines[-2:]:
            edge[b.text] += 1
    running = {t for t, n in edge.items() if n >= 3 and n >= len(pages) * 0.3}
    out = []
    for lines in pages:
        for i, b in enumerate(lines):
            edge_line = i < 2 or i >= len(lines) - 2
            if b.text in running or PAGE_NO.match(b.text) or (edge_line and re.fullmatch(r"\d{1,3}", b.text)):
                continue
            out.append(b)
    return out
