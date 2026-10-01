from reg.structure.model import Block


def extract(data: bytes, mime: str, filename: str) -> list[Block]:
    if mime == "application/pdf":
        from reg.extract.pdf import extract_pdf
        return extract_pdf(data)
    if mime == "application/x-hwp":
        from reg.extract.hwp import extract_hwp
        return extract_hwp(data)
    if mime == "application/hwp+zip":
        from reg.extract.hwpx import extract_hwpx
        return extract_hwpx(data)
    raise ValueError(f"지원하지 않는 형식: {mime} ({filename})")
