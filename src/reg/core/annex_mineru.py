# src/reg/core/annex_mineru.py
"""MinerU 4(GPU PC)를 별표 표 변환 엔진(TableSource)으로 감싼다. 클라이언트는 M6-5의 reg.platform.mineru.

V1 API는 markdown·middle_json·structured_content·zip만 낸다(content_list 없음, M6-5 실측).
표는 middle_json 블록 {"type": "table", "bbox": [0~1 정규화], "content": [{"type": "table_body", "content": "<table>…"}]}.
page_idx는 원본 문서 기준 0부터다(page_range를 줘도 원래 쪽 번호).
"""
import pypdfium2 as pdfium

from reg.core.annex_tables import TableBlock, TableSourceError, TableSourceUnavailable


def page_range(pages: list[int]) -> str:
    """[48, 49, 50, 60] → '48-50,60' (MinerU page_range는 1부터)."""
    out, ps, i = [], sorted(set(pages)), 0
    while i < len(ps):
        j = i
        while j + 1 < len(ps) and ps[j + 1] == ps[j] + 1:
            j += 1
        out.append(f"{ps[i]}-{ps[j]}" if j > i else str(ps[i]))
        i = j + 1
    return ",".join(out)


def tables_from_middle_json(middle: dict, sizes: list[tuple[float, float]]) -> list[TableBlock]:
    out = []
    for page in middle.get("pages") or []:
        no = int(page.get("page_idx", 0)) + 1
        size = sizes[no - 1] if 0 < no <= len(sizes) else None
        for block in sorted(page.get("blocks") or [], key=lambda b: b.get("index", 0)):
            if block.get("type") != "table":
                continue
            body = next((c.get("content") for c in block.get("content") or []
                         if c.get("type") == "table_body" and isinstance(c.get("content"), str)), None)
            if not body:
                continue
            b = block.get("bbox")
            bbox = (b[0] * size[0], b[1] * size[1], b[2] * size[0], b[3] * size[1]) \
                if size and isinstance(b, list | tuple) and len(b) == 4 else None
            out.append(TableBlock(no, bbox, body))
    return out


class MineruTables:
    name = "mineru"

    def __init__(self, client):
        self.client = client

    def tables(self, pdf: bytes, pages: list[int]) -> list[TableBlock]:
        from reg.platform.mineru import MineruError, MineruUnavailable

        try:
            res = self.client.parse(pdf, "view.pdf", tier="standard", ocr_mode="auto",
                                    output_formats=("middle_json",), page_range=page_range(pages))
        except MineruUnavailable as e:
            raise TableSourceUnavailable(str(e)) from e
        except MineruError as e:
            raise TableSourceError(str(e)) from e
        doc = pdfium.PdfDocument(pdf)
        try:
            sizes = [doc[i].get_size() for i in range(len(doc))]
        finally:
            doc.close()
        return tables_from_middle_json(res.middle_json or {}, sizes)


def mineru_source() -> MineruTables | None:
    """REG_MINERU_URL이 비어 있으면 None: 표 변환 단계를 건너뛴다 (기능 플래그, R8)."""
    from reg.platform.mineru import MineruClient
    from reg.platform.settings import get_settings

    s = get_settings()
    if not getattr(s, "mineru_url", ""):
        return None
    return MineruTables(MineruClient.from_settings(s, max_wait=600.0))
