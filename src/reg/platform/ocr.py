"""OCR 이음매(OcrEngine)와 MinerU 구현(MineruOcr).

결과는 읽는 순서의 줄(OcrLine: text, page 1부터, bbox)이다. 처리기가 core Block으로 바꿔 파싱한다.
bbox는 원본 PDF의 pt 좌표다(왼쪽 위 원점, pdfplumber·extract_pdf와 같은 계). 그래서 보기 화면은 원본 PDF 그대로
조문 위치를 강조한다. 다른 엔진(예: Tesseract, 계획 R1 예비안)도 이 프로토콜로 꽂는다.
"""
import io
import json
from dataclasses import dataclass
from typing import Protocol

import pdfplumber

from reg.platform.mineru import MineruClient, MineruError, MineruUnavailable, text_lines


class OcrError(Exception):
    """이 문서의 OCR이 실패했다. 시도 1회로 센다."""


class OcrUnavailable(Exception):
    """OCR 서비스에 닿지 않는다(GPU PC 꺼짐·재시작). 시도로 세지 않고 나중에 다시 한다."""


@dataclass(frozen=True)
class OcrLine:
    text: str
    page: int
    bbox: tuple[float, float, float, float] | None = None


@dataclass(frozen=True)
class OcrResult:
    lines: list[OcrLine]
    markdown: str
    raw: dict  # 엔진 원본 결과 (MinerU middle_json)
    engine: str  # source_document.ocr_engine에 남길 이름·버전


class OcrEngine(Protocol):
    name: str

    def available(self) -> bool: ...

    def ocr(self, pdf: bytes) -> OcrResult: ...


def pdf_page_sizes(pdf: bytes) -> dict[int, tuple[float, float]]:
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        return {i: (float(p.width), float(p.height)) for i, p in enumerate(doc.pages)}


def dump_lines(lines: list[OcrLine]) -> bytes:
    return json.dumps([{"text": ln.text, "page": ln.page, "bbox": list(ln.bbox) if ln.bbox else None}
                       for ln in lines], ensure_ascii=False).encode("utf-8")


def load_lines(data: bytes) -> list[OcrLine]:
    return [OcrLine(d["text"], d["page"], tuple(d["bbox"]) if d.get("bbox") else None) for d in json.loads(data)]


class MineruOcr:
    def __init__(self, client: MineruClient, tier: str = "standard"):
        self.client, self.tier = client, tier
        self.name = f"mineru-{tier}"

    def available(self) -> bool:
        return self.client.available(need=("middle_json", "markdown"))

    def ocr(self, pdf: bytes) -> OcrResult:
        try:  # ocr_mode=ocr: 깨진 글자 층을 믿지 않고 다시 읽는다 (계획 R2)
            r = self.client.parse(pdf, "source.pdf", tier=self.tier, ocr_mode="ocr",
                                  output_formats=("middle_json", "markdown"))
        except MineruUnavailable as e:
            raise OcrUnavailable(str(e)) from e
        except MineruError as e:
            raise OcrError(str(e)) from e
        try:
            sizes = pdf_page_sizes(pdf)
        except Exception as e:
            raise OcrError(f"원본 PDF 쪽 크기를 읽지 못함: {e}") from e
        lines = [OcrLine(d["text"], d["page"], tuple(d["bbox"]) if d["bbox"] else None)
                 for d in text_lines(r.middle_json or {}, sizes)]
        if not lines:
            raise OcrError(f"MinerU 결과에 글이 없음 (작업 {r.job_id})")
        return OcrResult(lines, r.markdown or "", r.middle_json or {},
                         f"mineru-{r.parser_version or 'unknown'}-{self.tier}")
