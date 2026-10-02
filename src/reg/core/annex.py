# src/reg/core/annex.py
"""별표·별지 영역 이미지 (M6-6 1단계: 이 서버 CPU, pypdfium2).

영역 = 별표 머리 줄의 위치(anchor)부터, 문서 순서상 다음 위치가 있는 조항의 머리 줄 직전까지.
여러 쪽에 걸치면 쪽(두 쪽 모아찍기면 반쪽)마다 한 조각. 조각마다 PNG 하나를 보관소에 둔다 (R7).

보관소 키 (원본 sha256 기준이라 재파싱해도 위치가 같으면 다시 그리지 않는다)
- annex/{sha256}/{path}.png        첫 조각
- annex/{sha256}/{path}@{n}.png    n번째 조각 (n ≥ 2)
- annex/{sha256}/{path}.html       표 HTML (2단계, reg.core.annex_tables)
- annex/{sha256}/manifest.json     조각 목록 · 위치 요약값 · 표 상태
"""
import hashlib
import io
import json
from dataclasses import asdict, dataclass

import pypdfium2 as pdfium

from reg.core.extract.layout import two_up_gutter

RENDER_SCALE = 2.0      # 144 dpi: 글자가 또렷하고 쪽당 100~300 KB
TOP_PAD = 6.0           # 머리 줄 위 여백 (pt)
MIN_TAIL = 0.12         # 마지막 조각이 쪽 높이의 이 비율보다 작으면(머리글뿐) 버린다
MAX_SEGMENTS = 30       # 별표 하나에 그리는 조각 상한 (위치를 잘못 찾아 문서 끝까지 가는 경우 대비)


@dataclass(frozen=True)
class Segment:
    page: int                                   # 1부터 (물리 쪽)
    box: tuple[float, float, float, float]      # x0, top, x1, bottom — pt, 왼쪽 위 원점


@dataclass(frozen=True)
class PageLayout:
    width: float
    height: float
    gutter: float | None                        # 두 쪽 모아찍기면 가운데 x


def page_layouts(pdf: bytes) -> list[PageLayout]:
    doc = pdfium.PdfDocument(pdf)
    out = []
    for page in doc:
        w, h = page.get_size()
        tp = page.get_textpage()
        boxes = [(r[0], r[2]) for r in (tp.get_rect(i) for i in range(tp.count_rects()))]
        out.append(PageLayout(w, h, two_up_gutter(boxes, w, h)))
    doc.close()
    return out


def _units(layouts: list[PageLayout]) -> list[tuple[int, float, float]]:
    """읽기 단위 (쪽, x0, x1): 모아찍기 쪽은 왼쪽·오른쪽 반쪽 두 개."""
    out = []
    for no, lay in enumerate(layouts, 1):
        if lay.gutter is None:
            out.append((no, 0.0, lay.width))
        else:
            out += [(no, 0.0, lay.gutter), (no, lay.gutter, lay.width)]
    return out


def _unit_of(units, page: int, bbox) -> int:
    cx = (bbox[0] + bbox[2]) / 2 if bbox else 0.0
    cand = [i for i, (p, _, _) in enumerate(units) if p == page]
    return next((i for i in cand if units[i][1] <= cx < units[i][2]), cand[0])


def annex_regions(order: list[dict], layouts: list[PageLayout]) -> dict[str, list[Segment]]:
    """order: 판본의 조항을 문서 순서대로 [{path, unit, anchor}] (version_provision.ord 순)."""
    units = _units(layouts)
    out: dict[str, list[Segment]] = {}
    anchored = [o for o in order if o.get("anchor") and o["anchor"].get("page") and o["anchor"].get("bbox")
                and o["anchor"]["page"] <= len(layouts)]
    for k, o in enumerate(anchored):
        if o["unit"] != "annex":
            continue
        a = o["anchor"]
        su = _unit_of(units, a["page"], a["bbox"])
        nxt = anchored[k + 1]["anchor"] if k + 1 < len(anchored) else None
        if nxt is None:
            eu = len(units) - 1                      # 마지막 별표: 문서 끝까지
        else:
            eu = _unit_of(units, nxt["page"], nxt["bbox"])
            if eu < su or (eu == su and nxt["bbox"][1] <= a["bbox"][1]):
                nxt, eu = None, su                   # 위치가 거꾸로면(잘못 찾은 위치) 시작 단위 끝까지만
        segs = []
        for ui in range(su, min(eu, su + MAX_SEGMENTS - 1) + 1):
            page, x0, x1 = units[ui]
            h = layouts[page - 1].height
            top = max(0.0, a["bbox"][1] - TOP_PAD) if ui == su else 0.0
            bottom = nxt["bbox"][1] - 2 if nxt and ui == eu else h
            if ui == eu and nxt and ui != su and bottom < h * MIN_TAIL:
                continue  # 다음 조항이 새 쪽 맨 위에서 시작: 머리글만 남은 조각
            if bottom - top >= 1:
                segs.append(Segment(page, (round(x0, 1), round(top, 1), round(x1, 1), round(bottom, 1))))
        if segs:
            out[o["path"]] = segs
    return out


def render_segment(doc: pdfium.PdfDocument, seg: Segment, scale: float = RENDER_SCALE) -> bytes:
    page = doc[seg.page - 1]
    w, h = page.get_size()
    x0, top, x1, bottom = seg.box
    img = page.render(scale=scale, crop=(x0, h - bottom, w - x1, top)).to_pil()  # crop: 왼·아래·오른·위에서 잘라낼 pt
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def image_key(sha: str, path: str, n: int) -> str:
    return f"annex/{sha}/{path}.png" if n == 1 else f"annex/{sha}/{path}@{n}.png"


def manifest_key(sha: str) -> str:
    return f"annex/{sha}/manifest.json"


def anchor_digest(order: list[dict]) -> str:
    """조항 위치가 그대로면 같은 값: 재파싱 뒤에도 영역이 같으면 다시 그리지 않는다."""
    raw = json.dumps([(o["path"], o.get("anchor")) for o in order], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def load_manifest(blob, sha: str) -> dict:
    key = manifest_key(sha)
    return json.loads(blob.get(key)) if blob.exists(key) else {"digest": None, "items": {}}


def save_manifest(blob, sha: str, man: dict) -> None:
    blob.put(manifest_key(sha), json.dumps(man, ensure_ascii=False).encode(), "application/json")


def version_order(conn, version_id: str) -> tuple[dict | None, list[dict]]:
    """판본의 원본 정보(sha256, 보기용 PDF 키)와 문서 순서의 조항 위치."""
    sd = conn.execute("SELECT sd.sha256, sd.view_blob_key FROM regulation.work_version v"
                      " JOIN regulation.source_document sd ON sd.id = v.source_document_id WHERE v.id = %s",
                      (version_id,)).fetchone()
    rows = conn.execute("SELECT pv.path, pv.unit, coalesce(vp.anchor, pv.source_anchor) AS anchor"
                        " FROM regulation.version_provision vp JOIN regulation.provision_version pv"
                        " ON pv.id = vp.provision_version_id WHERE vp.work_version_id = %s ORDER BY vp.ord",
                        (version_id,)).fetchall()
    return sd, [dict(r) for r in rows]


def ensure_rendered(conn, blob, version_id: str) -> dict:
    """판본의 모든 별표 영역 이미지를 만들어 두고 매니페스트를 돌려준다. 이미 같은 위치로 만들었으면 그대로."""
    sd, order = version_order(conn, version_id)
    if not sd or not sd["view_blob_key"]:
        return {"digest": None, "items": {}, "reason": "no_view_pdf"}
    man = load_manifest(blob, sd["sha256"])
    digest = anchor_digest(order)
    if man.get("digest") == digest:
        return man
    pdf = blob.get(sd["view_blob_key"])
    regions = annex_regions(order, page_layouts(pdf))
    doc = pdfium.PdfDocument(pdf)
    try:
        items = {}
        for path, segs in regions.items():
            keys = []
            for n, seg in enumerate(segs, 1):
                key = image_key(sd["sha256"], path, n)
                blob.put(key, render_segment(doc, seg), "image/png")
                keys.append({"key": key, **asdict(seg)})
            old = man.get("items", {}).get(path, {})
            items[path] = {"segments": keys, "table": old.get("table", {"status": "none"})}
    finally:
        doc.close()
    man = {"digest": digest, "items": items}
    save_manifest(blob, sd["sha256"], man)
    return man
