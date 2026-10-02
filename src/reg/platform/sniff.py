from typing import NamedTuple

OLE_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")


class FileKind(NamedTuple):
    mime: str
    ext: str


def sniff(content: bytes, filename: str) -> FileKind | None:
    """허용 형식(PDF, HWP 5.0, HWPX)만 인정한다. 오류 페이지나 기타 형식은 None."""
    name = filename.lower()
    if content.startswith(b"%PDF"):
        return FileKind("application/pdf", "pdf")
    if content.startswith(OLE_MAGIC):
        return FileKind("application/x-hwp", "hwp")
    if content.startswith(b"PK\x03\x04") and name.endswith(".hwpx"):
        return FileKind("application/hwp+zip", "hwpx")
    return None
