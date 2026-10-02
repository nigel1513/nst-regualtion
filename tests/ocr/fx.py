"""OCR 테스트 공용: 표본 경로, 가짜 엔진."""
from pathlib import Path

from reg.platform.ocr import OcrError, OcrLine, OcrResult, OcrUnavailable
from tests.test_process import FX

BROKEN = FX / "ocr" / "kasi-radiation-727-broken-digits.pdf"  # KASI 방사선재해보상기준: 조문 번호 숫자가 글자 층에서 빠짐
SCAN = FX / "ocr" / "kasi-severance-483-scan.pdf"  # KASI 퇴직금지급요령: 스캔본(한글 글자 층 없음)
TEXT_PDF = FX / "samples" / "kasi-yeobi-339.pdf"  # 글자 층이 멀쩡한 규정 PDF (가짜 OCR 결과의 재료)


def lines_of(path: Path) -> list[OcrLine]:
    from reg.core.extract.pdf import extract_pdf

    return [OcrLine(b.text, b.page, b.bbox) for b in extract_pdf(path.read_bytes())]


class FakeOcr:
    name = "fake"

    def __init__(self, lines: list[OcrLine] | None = None, fail: int = 0, healthy: bool = True,
                 unavailable: bool = False):
        self.lines, self.fail, self.healthy, self.unavailable, self.calls = lines or [], fail, healthy, unavailable, 0

    def available(self) -> bool:
        return self.healthy

    def ocr(self, pdf: bytes) -> OcrResult:
        self.calls += 1
        if self.unavailable:
            raise OcrUnavailable("MinerU 작업 job_1이 사라짐 (서비스 재시작)")
        if self.calls <= self.fail:
            raise OcrError(f"가짜 실패 {self.calls}")
        return OcrResult(self.lines, "# 가짜", {"pages": []}, "fake-1")
