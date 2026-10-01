import os

import pytest

from reg.storage.blob import LocalBlobStore, S3BlobStore, blob_key


def test_blob_key_layout():
    assert blob_key("alio", "abcdef", "pdf") == "raw/alio/ab/abcdef.pdf"


def test_local_roundtrip(tmp_path):
    s = LocalBlobStore(tmp_path)
    assert not s.exists("raw/x/ab/abc.pdf")
    s.put("raw/x/ab/abc.pdf", b"%PDF-1", "application/pdf")
    assert s.exists("raw/x/ab/abc.pdf")
    assert s.get("raw/x/ab/abc.pdf") == b"%PDF-1"


@pytest.mark.integration
def test_s3_roundtrip_live():
    from reg.settings import get_settings

    st = get_settings()
    s = S3BlobStore(st.s3_endpoint, st.s3_bucket, st.s3_access_key, st.s3_secret_key)
    s.ensure_bucket()
    s.put("test/hello.txt", b"hi", "text/plain")
    assert s.exists("test/hello.txt") and s.get("test/hello.txt") == b"hi"

