"""HWPX(OWPML, zip) 본문 문단 추출. 표 안의 문단은 바깥 문단과 섞지 않고 따로 낸다."""
import io
import re
import xml.etree.ElementTree as ET
import zipfile

from reg.structure.model import Block
from reg.structure.text import clean


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _walk(elem, buf: list[str] | None, out: list[str]) -> None:
    if _local(elem.tag) == "p":
        mine: list[str] = []
        for child in elem:
            _walk(child, mine, out)
        t = clean("".join(mine))
        if t:
            out.append(t)
        return
    if _local(elem.tag) == "t" and buf is not None:
        buf.append(elem.text or "")
    for child in elem:
        _walk(child, buf, out)
        if _local(elem.tag) == "t" and buf is not None and child.tail:
            buf.append(child.tail)


def extract_hwpx(data: bytes) -> list[Block]:
    z = zipfile.ZipFile(io.BytesIO(data))
    names = sorted((n for n in z.namelist() if re.match(r"Contents/section\d+\.xml$", n)),
                   key=lambda n: int(re.search(r"(\d+)", n)[1]))
    out: list[str] = []
    for n in names:
        _walk(ET.fromstring(z.read(n)), None, out)
    return [Block(t) for t in out]
