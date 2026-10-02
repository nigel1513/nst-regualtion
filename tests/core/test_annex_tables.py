# tests/core/test_annex_tables.py
from reg.core.annex import image_key
from reg.core.annex_mineru import MineruTables, page_range, tables_from_middle_json
from reg.core.annex_tables import (
    TableBlock,
    TableSourceError,
    TableSourceUnavailable,
    assign_tables,
    convert_version,
    sanitize_table_html,
    table_key,
)
from reg.platform.storage.blob import LocalBlobStore
from tests.core.helpers import PDF, load_pdf_version


class FakeSource:
    name = "fake"

    def __init__(self, result):
        self.result, self.calls = result, 0

    def tables(self, pdf, pages):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_sanitizer_keeps_table_structure_only():
    raw = ('<table onclick="x()"><tr><td colspan="2" style="a">가<script>alert(1)</script></td>'
           '<td rowspan="x">나 &amp; <a href="javascript:1">다</a></td></tr></table>')
    assert sanitize_table_html(raw) == '<table><tr><td colspan="2">가</td><td>나 &amp; 다</td></tr></table>'


def test_middle_json_tables_scale_to_points_and_page_range():
    middle = {"pages": [{"page_idx": 1, "blocks": [
        {"type": "text", "index": 0, "bbox": [0.1, 0.1, 0.9, 0.2], "content": [{"type": "text", "content": "x"}]},
        {"type": "table", "index": 1, "bbox": [0.1, 0.5, 0.9, 0.7],
         "content": [{"type": "table_body", "content": "<table></table>"}]}]}]}
    t = tables_from_middle_json(middle, [(595.0, 841.0), (595.0, 841.0)])
    assert len(t) == 1 and t[0].page == 2 and t[0].html == "<table></table>"
    assert [round(x, 1) for x in t[0].bbox] == [59.5, 420.5, 535.5, 588.7]
    assert page_range([48, 49, 50, 60]) == "48-50,60"


def test_assign_tables_uses_vertical_center():
    items = {"annex1": {"segments": [{"page": 3, "box": [0, 0, 595, 400]}]},
             "annex2": {"segments": [{"page": 3, "box": [0, 400, 595, 841]}]}}
    got = assign_tables(items, [TableBlock(3, (0, 500, 595, 700), "<table/>"), TableBlock(4, None, "x")])
    assert list(got) == ["annex2"]


def test_convert_version_degrades_and_retries(conn, tmp_path):
    blob = LocalBlobStore(tmp_path)
    vid, sha = load_pdf_version(conn, blob, "kasi_form4_p48-49.pdf")
    down = FakeSource(TableSourceUnavailable("connect timeout"))
    assert convert_version(conn, blob, vid, down)["unavailable"] == 2
    assert blob.exists(image_key(sha, "form4", 1))  # 엔진이 꺼져도 이미지는 있다
    up = FakeSource([TableBlock(1, (100.0, 150.0, 500.0, 600.0), "<table><tr><td>요구부서</td></tr></table>")])
    st = convert_version(conn, blob, vid, up)
    assert (st["ok"], st["no_table"]) == (1, 1)
    assert b"<td>" in blob.get(table_key(sha, "form4"))
    again = convert_version(conn, blob, vid, up)
    assert again == {"annexes": 0, "ok": 0, "no_table": 0, "failed": 0, "unavailable": 0} and up.calls == 1


def test_convert_version_gives_up_after_three_errors(conn, tmp_path):
    blob = LocalBlobStore(tmp_path)
    vid, _ = load_pdf_version(conn, blob, "kasi_form4_p48-49.pdf")
    bad = FakeSource(TableSourceError("422 unsupported"))
    for _ in range(4):
        convert_version(conn, blob, vid, bad)
    assert bad.calls == 3


def test_mineru_adapter_maps_client_errors(monkeypatch):
    import sys
    import types

    class MineruError(Exception):
        pass

    class MineruUnavailable(Exception):
        pass

    monkeypatch.setitem(sys.modules, "reg.platform.mineru",
                        types.SimpleNamespace(MineruError=MineruError, MineruUnavailable=MineruUnavailable))

    class Client:
        def __init__(self, exc=None):
            self.exc, self.kw = exc, None

        def parse(self, data, filename, **kw):
            self.kw = kw
            if self.exc:
                raise self.exc
            return types.SimpleNamespace(middle_json={"pages": []})

    pdf = (PDF / "kasi_form4_p48-49.pdf").read_bytes()
    c = Client()
    assert MineruTables(c).tables(pdf, [1, 2]) == []
    assert c.kw == {"tier": "standard", "ocr_mode": "auto", "output_formats": ("middle_json",), "page_range": "1-2"}
    for exc, want in ((MineruUnavailable("down"), TableSourceUnavailable), (MineruError("bad"), TableSourceError)):
        try:
            MineruTables(Client(exc)).tables(pdf, [1])
        except want:
            pass
        else:
            raise AssertionError(want)

