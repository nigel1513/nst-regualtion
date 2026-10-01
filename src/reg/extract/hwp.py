"""HWP 5.0 본문 문단 추출 (OLE BodyText/Section*, HWPTAG_PARA_TEXT=67)."""
import io
import struct
import zlib

import olefile

from reg.structure.model import Block
from reg.structure.text import clean

PARA_TEXT = 67
# HWP 5.0 문자 컨트롤: 확장·인라인 컨트롤은 WCHAR 8개를 차지한다
_WIDE = {1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23}


def _para_text(raw: bytes) -> str:
    chars = struct.unpack(f"<{len(raw) // 2}H", raw[: len(raw) // 2 * 2])
    out, i = [], 0
    while i < len(chars):
        c = chars[i]
        if c in _WIDE:
            i += 8
            continue
        if c >= 32:
            out.append(chr(c))
        elif c in (10, 13):
            out.append(" ")
        i += 1
    return "".join(out)


def extract_hwp(data: bytes) -> list[Block]:
    ole = olefile.OleFileIO(io.BytesIO(data))
    compressed = ole.openstream("FileHeader").read()[36] & 1
    sections = sorted((e for e in ole.listdir() if e[0] == "BodyText"), key=lambda e: int(e[1][7:]))
    blocks = []
    for sec in sections:
        buf = ole.openstream(sec).read()
        if compressed:
            buf = zlib.decompress(buf, -15)
        i = 0
        while i + 4 <= len(buf):
            header = struct.unpack_from("<I", buf, i)[0]
            tag, size = header & 0x3FF, (header >> 20) & 0xFFF
            i += 4
            if size == 0xFFF:
                size = struct.unpack_from("<I", buf, i)[0]
                i += 4
            if tag == PARA_TEXT:
                t = clean(_para_text(buf[i:i + size]))
                if t:
                    blocks.append(Block(t))
            i += size
    return blocks
