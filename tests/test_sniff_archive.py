from reg.collect.archive import store
from reg.collect.sniff import sniff
from reg.storage.blob import LocalBlobStore

OLE = bytes.fromhex("D0CF11E0A1B11AE1") + b"\x00" * 8


def test_sniff_kinds():
    assert sniff(b"%PDF-1.4 ...", "a.pdf").ext == "pdf"
    assert sniff(OLE, "a.hwp").ext == "hwp"
    assert sniff(b"PK\x03\x04....", "a.hwpx").ext == "hwpx"
    assert sniff(b"PK\x03\x04....", "a.zip") is None
    assert sniff(b"<html>error</html>", "a.pdf") is None
    assert sniff(b"", "a.pdf") is None


def test_store_dedupes_by_content(conn, tmp_path):
    blob = LocalBlobStore(tmp_path)
    k = sniff(b"%PDF-1.4 x", "a.pdf")
    a = store(conn, blob, source="alio", url="u1", content=b"%PDF-1.4 x", kind=k, meta={"f": 1})
    b = store(conn, blob, source="alio", url="u2", content=b"%PDF-1.4 x", kind=k, meta={"f": 2})
    assert a.is_new and not b.is_new and a.id == b.id
    assert blob.get(a.blob_key) == b"%PDF-1.4 x"
    assert conn.execute("SELECT count(*) AS n FROM regulation.source_document").fetchone()["n"] == 1
