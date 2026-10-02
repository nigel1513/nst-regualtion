# tests/api/test_annex_routes.py
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from reg.api.app import create_app
from reg.core.annex_tables import TableBlock, convert_version
from reg.platform.storage.blob import LocalBlobStore
from tests.core.helpers import load_pdf_version


@pytest.fixture
def annex_api(conn, migrated, tmp_path):
    blob = LocalBlobStore(tmp_path)
    vid, _ = load_pdf_version(conn, blob, "kasi_form4_p48-49.pdf")
    with TestClient(create_app(migrated[0], blob)) as c:
        yield c, vid, conn, blob


def test_annex_meta_and_image(annex_api):
    api, vid, _, _ = annex_api
    m = api.get("/api/v1/annex", params={"version": vid, "path": "form4"}).json()
    assert m["page"] == 1 and m["table"] == {"status": "none", "url": None}
    url = m["segments"][0]["url"]
    assert parse_qs(urlparse(url).query)["version"] == [vid]  # 판본 id의 '/'·'@'·한글이 인코딩돼 있다
    img = api.get(url)
    assert img.status_code == 200 and img.headers["content-type"] == "image/png" and img.content[:4] == b"\x89PNG"
    assert api.get("/api/v1/annex/image", params={"version": vid, "path": "form4", "n": 2}).status_code == 404


def test_annex_errors(annex_api):
    api, vid, _, _ = annex_api
    assert api.get("/api/v1/annex", params={"version": "kr/reg/X@2020-01-01", "path": "annex1"}).status_code == 404
    assert api.get("/api/v1/annex", params={"version": vid, "path": "annex9"}).status_code == 404
    assert api.get("/api/v1/annex", params={"version": vid, "path": "../etc"}).status_code == 422
    assert api.get("/api/v1/annex/table", params={"version": vid, "path": "form4"}).status_code == 404


def test_annex_without_view_pdf_is_404(annex_api):
    """Review Focus 4: HWP 변환 실패 판본."""
    api, vid, conn, _ = annex_api
    conn.execute("UPDATE regulation.source_document SET view_blob_key = NULL, view_status = 'failed'")
    conn.commit()
    r = api.get("/api/v1/annex", params={"version": vid, "path": "form4"})
    assert r.status_code == 404 and "이미지" in r.json()["detail"]


def test_annex_table_after_conversion(annex_api):
    api, vid, conn, blob = annex_api

    class Src:
        name = "fake"

        def tables(self, pdf, pages):
            return [TableBlock(1, (100.0, 150.0, 500.0, 600.0), "<table><tr><td>요구부서</td></tr></table>")]

    convert_version(conn, blob, vid, Src())
    m = api.get("/api/v1/annex", params={"version": vid, "path": "form4"}).json()
    assert m["table"]["status"] == "ok"
    assert api.get(m["table"]["url"]).json() == {"html": "<table><tr><td>요구부서</td></tr></table>"}
