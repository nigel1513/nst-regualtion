# src/reg/core/annex_tables.py
"""별표 표 → HTML (M6-6 2단계: GPU PC의 MinerU 4, R8).

- 별표 영역 이미지(1단계)가 먼저 있어야 한다. 표 변환은 그 위의 덧붙임이고, 실패해도 이미지·텍스트는 그대로다.
- 엔진에 닿지 못하면(TableSourceUnavailable) 상태를 'unavailable'로 두고 다음 실행에서 다시 한다. 시도 횟수는 늘리지 않는다.
- 변환 오류(TableSourceError)는 시도 횟수를 늘리고, MAX_ATTEMPTS번 실패하면 'failed'로 멈춘다.
- 결과 HTML은 허용 목록으로 정화해서 annex/{sha256}/{path}.html에 둔다.
"""
import html
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Protocol

from reg.core.annex import ensure_rendered, save_manifest, version_order

MAX_ATTEMPTS = 3
ALLOWED = {"table", "thead", "tbody", "tfoot", "tr", "td", "th", "caption", "colgroup", "col", "br", "p", "span",
           "b", "strong", "i", "em", "sub", "sup"}
ALLOWED_ATTRS = {"colspan", "rowspan"}
VOID = {"br", "col"}


@dataclass(frozen=True)
class TableBlock:
    page: int                                        # 1부터 (원본 PDF 물리 쪽)
    bbox: tuple[float, float, float, float] | None   # x0, top, x1, bottom — pt, 왼쪽 위 원점 (모르면 None)
    html: str


class TableSource(Protocol):
    name: str

    def tables(self, pdf: bytes, pages: list[int]) -> list[TableBlock]: ...


class TableSourceUnavailable(Exception):
    """엔진에 닿지 못함 (GPU PC 꺼짐·네트워크). 다음 실행에서 다시 한다."""


class TableSourceError(Exception):
    """엔진이 이 문서를 처리하지 못함."""


class _Sanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0  # script·style 안

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
            return
        if tag in ALLOWED and not self.skip:
            kept = "".join(f' {k}="{html.escape(v or "", quote=True)}"' for k, v in attrs
                           if k in ALLOWED_ATTRS and (v or "").isdigit())
            self.out.append(f"<{tag}{kept}>")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
            return
        if tag in ALLOWED and tag not in VOID and not self.skip:
            self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(html.escape(data, quote=False))


def sanitize_table_html(raw: str) -> str:
    s = _Sanitizer()
    s.feed(raw or "")
    s.close()
    return "".join(s.out)


def table_key(sha: str, path: str) -> str:
    return f"annex/{sha}/{path}.html"


def _overlaps(tb: TableBlock, seg: dict) -> bool:
    if tb.page != seg["page"]:
        return False
    if tb.bbox is None:
        return True
    cy = (tb.bbox[1] + tb.bbox[3]) / 2
    return seg["box"][1] <= cy <= seg["box"][3]


def assign_tables(items: dict, tables: list[TableBlock]) -> dict[str, list[TableBlock]]:
    """표마다 그 가운데가 들어가는 별표 조각을 찾는다."""
    out: dict[str, list[TableBlock]] = {}
    for tb in tables:
        for path, it in items.items():
            if any(_overlaps(tb, s) for s in it["segments"]):
                out.setdefault(path, []).append(tb)
                break
    return out


def _todo(it: dict) -> bool:
    t = it.get("table", {})
    return t.get("status", "none") in ("none", "unavailable") or (
        t.get("status") == "failed" and t.get("attempts", 0) < MAX_ATTEMPTS)


def convert_version(conn, blob, version_id: str, source: TableSource) -> dict:
    """판본의 별표 중 아직 표 변환을 안 했거나 다시 할 것만 엔진에 보낸다 (한 판본 = 엔진 호출 한 번)."""
    man = ensure_rendered(conn, blob, version_id)
    todo = {p: it for p, it in man.get("items", {}).items() if _todo(it)}
    st = {"annexes": len(todo), "ok": 0, "no_table": 0, "failed": 0, "unavailable": 0}
    if not todo:
        return st
    sd, _ = version_order(conn, version_id)
    pages = sorted({s["page"] for it in todo.values() for s in it["segments"]})
    now = datetime.now(UTC).isoformat(timespec="seconds")
    try:
        tables = source.tables(blob.get(sd["view_blob_key"]), pages)
    except TableSourceUnavailable:
        for it in todo.values():
            it["table"] = {**it.get("table", {}), "status": "unavailable", "at": now}
        st["unavailable"] = len(todo)
        save_manifest(blob, sd["sha256"], man)
        return st
    except TableSourceError as e:
        for it in todo.values():
            n = it.get("table", {}).get("attempts", 0) + 1
            it["table"] = {"status": "failed", "attempts": n, "error": str(e)[:300], "at": now}
        st["failed"] = len(todo)
        save_manifest(blob, sd["sha256"], man)
        return st
    found = assign_tables(todo, tables)
    for path, it in todo.items():
        body = "".join(sanitize_table_html(t.html) for t in found.get(path, []))
        if body:
            blob.put(table_key(sd["sha256"], path), body.encode("utf-8"), "text/html; charset=utf-8")
            it["table"] = {"status": "ok", "engine": source.name, "tables": len(found[path]), "at": now}
            st["ok"] += 1
        else:
            it["table"] = {"status": "no_table", "engine": source.name, "at": now}
            st["no_table"] += 1
    save_manifest(blob, sd["sha256"], man)
    return st
