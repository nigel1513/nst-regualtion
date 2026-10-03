import io
from typing import NamedTuple

OLE_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")
# HWP 5.0과 MS Office 97-2003(xls·doc·ppt)은 같은 OLE 머리를 쓴다
OFFICE_EXT = (".xls", ".doc", ".ppt", ".xlsx", ".docx", ".pptx")
OFFICE_STREAMS = ("Workbook", "Book", "WordDocument", "PowerPoint Document")


class FileKind(NamedTuple):
    mime: str
    ext: str


def sniff(content: bytes, filename: str) -> FileKind | None:
    """허용 형식(PDF, HWP 5.0, HWPX)만 인정한다. 오류 페이지나 기타 형식은 None."""
    name = filename.lower()
    if content.startswith(b"%PDF"):
        return FileKind("application/pdf", "pdf")
    if content.startswith(OLE_MAGIC):
        return FileKind("application/x-hwp", "hwp") if _ole_is_hwp(content, name) else None
    if content.startswith(b"PK\x03\x04") and name.endswith(".hwpx"):
        return FileKind("application/hwp+zip", "hwpx")
    return None


def _ole_is_hwp(content: bytes, name: str) -> bool:
    """OLE 파일 중 HWP만: 이름이 Office 확장자거나, 열어 봐서 Office 스트림이 있으면 HWP가 아니다."""
    if name.endswith(OFFICE_EXT):
        return False
    try:
        import olefile

        ole = olefile.OleFileIO(io.BytesIO(content))
    except Exception:  # 머리만 있는 조각 등 열 수 없으면 예전처럼 HWP로 보고 추출 단계가 판단한다
        return True
    try:
        if ole.exists("FileHeader"):
            return True
        return not any(ole.exists(s) for s in OFFICE_STREAMS)
    finally:
        ole.close()
