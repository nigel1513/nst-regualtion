# tests/core/test_annex.py
from reg.core.annex import Segment, annex_regions, ensure_rendered, image_key, page_layouts
from reg.platform.storage.blob import LocalBlobStore
from tests.core.helpers import PDF, load_pdf_version


def test_regions_follow_anchors_and_drop_header_only_tail():
    lay = page_layouts((PDF / "kasi_form4_p48-49.pdf").read_bytes())
    order = [{"path": "a1", "unit": "article", "anchor": {"page": 1, "bbox": [82.2, 60.0, 400.0, 70.0]}},
             {"path": "form4", "unit": "annex", "anchor": {"page": 1, "bbox": [82.2, 101.9, 160.1, 112.9]}},
             {"path": "form5", "unit": "annex", "anchor": {"page": 2, "bbox": [82.2, 101.9, 256.4, 112.9]}}]
    r = annex_regions(order, lay)
    assert r["form4"] == [Segment(1, (0.0, 95.9, 595.0, 841.0))]  # 다음 쪽 머리글(위 12%)만 남는 조각은 버린다
    assert r["form5"] == [Segment(2, (0.0, 95.9, 595.0, 841.0))]


def test_regions_on_two_up_sheet_stay_in_one_half():
    lay = page_layouts((PDF / "etri_twoup_research_mgmt_p2-3.pdf").read_bytes())
    assert lay[0].gutter == 420.5
    order = [{"path": "annex1", "unit": "annex", "anchor": {"page": 1, "bbox": [500.0, 100.0, 700.0, 110.0]}},
             {"path": "annex2", "unit": "annex", "anchor": {"page": 2, "bbox": [80.0, 300.0, 300.0, 310.0]}}]
    r = annex_regions(order, lay)
    assert [s.box[0] for s in r["annex1"]] == [420.5, 0.0]  # 1쪽 오른쪽 반 → 2쪽 왼쪽 반
    assert r["annex1"][1].box[3] == 298.0


def test_inverted_or_missing_next_anchor_stays_on_start_unit():
    """Review Focus 3."""
    lay = page_layouts((PDF / "kasi_form4_p48-49.pdf").read_bytes())
    order = [{"path": "form5", "unit": "annex", "anchor": {"page": 2, "bbox": [82.2, 101.9, 256.4, 112.9]}},
             {"path": "a9", "unit": "article", "anchor": {"page": 1, "bbox": [82.2, 300.0, 400.0, 310.0]}},
             {"path": "form6", "unit": "annex", "anchor": {"page": 1, "bbox": [82.2, 500.0, 160.0, 510.0]}}]
    r = annex_regions(order, lay)
    assert r["form5"] == [Segment(2, (0.0, 95.9, 595.0, 841.0))]  # 다음 위치(1쪽)가 앞이면 그 쪽 끝까지만
    assert r["form6"] == [Segment(1, (0.0, 494.0, 595.0, 841.0)), Segment(2, (0.0, 0.0, 595.0, 841.0))]  # 마지막: 끝까지


def test_ensure_rendered_writes_pngs_once(conn, tmp_path):
    blob = LocalBlobStore(tmp_path)
    vid, sha = load_pdf_version(conn, blob, "kasi_form4_p48-49.pdf")
    man = ensure_rendered(conn, blob, vid)
    assert set(man["items"]) == {"form4", "form5"}
    png = blob.get(image_key(sha, "form4", 1))
    assert png.startswith(b"\x89PNG") and len(png) > 20_000
    blob.put(image_key(sha, "form4", 1), b"sentinel", "image/png")
    ensure_rendered(conn, blob, vid)  # 위치가 같으면 다시 그리지 않는다
    assert blob.get(image_key(sha, "form4", 1)) == b"sentinel"


def test_rerender_only_when_anchors_change(conn, tmp_path):
    """Review Focus 5."""
    blob = LocalBlobStore(tmp_path)
    vid, _ = load_pdf_version(conn, blob, "kasi_form4_p48-49.pdf")
    first = ensure_rendered(conn, blob, vid)
    conn.execute("UPDATE regulation.version_provision SET anchor = jsonb_set(anchor, '{bbox,1}', '300')"
                 " WHERE work_version_id = %s AND anchor IS NOT NULL AND ord = (SELECT max(ord)"
                 " FROM regulation.version_provision WHERE work_version_id = %s AND anchor IS NOT NULL)", (vid, vid))
    conn.commit()
    second = ensure_rendered(conn, blob, vid)
    assert second["digest"] != first["digest"]
    assert second["items"]["form5"]["segments"][0]["box"][1] == 294.0


def test_version_without_view_pdf_has_no_items(conn, tmp_path):
    blob = LocalBlobStore(tmp_path)
    vid, _ = load_pdf_version(conn, blob, "kasi_form4_p48-49.pdf")
    conn.execute("UPDATE regulation.source_document SET view_blob_key = NULL")
    conn.commit()
    assert ensure_rendered(conn, blob, vid) == {"digest": None, "items": {}, "reason": "no_view_pdf"}
