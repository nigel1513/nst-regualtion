from datetime import date
from pathlib import Path

from reg.core.ingest.process import process_once, rebuild_all
from reg.platform.storage.blob import LocalBlobStore
from tests.test_process import seed_alio

S = Path(__file__).parent / "fixtures" / "samples"
TODAY = date(2026, 10, 2)


class FakeConverter:
    def __init__(self, pdf: bytes | None):
        self.pdf, self.calls = pdf, 0

    def to_pdf(self, data, ext):
        self.calls += 1
        if self.pdf is None:
            from reg.platform.convert import ConversionError
            raise ConversionError("no docker")
        return self.pdf


def test_hwp_gets_view_pdf_anchors_refs_and_validation(conn, tmp_path):
    blob = LocalBlobStore(tmp_path)
    seed_alio(conn, blob, (S / "nst-yeobi-18.hwp").read_bytes(), file_name="여비규정(제18차 개정).hwp")
    conn.execute("UPDATE regulation.source_document SET mime='application/x-hwp'")
    conn.commit()
    conv = FakeConverter((S / "nst-yeobi-18.view.pdf").read_bytes())
    assert process_once(conn, blob, today=TODAY, converter=conv)["ok"] == 1
    sd = conn.execute("SELECT view_blob_key, view_status FROM regulation.source_document").fetchone()
    assert sd["view_status"] == "ready" and blob.exists(sd["view_blob_key"])
    a = conn.execute("SELECT source_anchor FROM regulation.provision_version WHERE path='a9-2'").fetchone()
    assert a["source_anchor"]["page"] == 5
    n = conn.execute("SELECT count(*) AS n FROM regulation.reference").fetchone()["n"]
    assert n > 10
    v = conn.execute("SELECT validation_status FROM regulation.work_version").fetchone()
    assert v["validation_status"] in ("PASSED", "REVIEW")


def test_converter_failure_does_not_fail_event(conn, tmp_path):
    blob = LocalBlobStore(tmp_path)
    seed_alio(conn, blob, (S / "nst-yeobi-18.hwp").read_bytes(), file_name="여비규정.hwp")
    conn.execute("UPDATE regulation.source_document SET mime='application/x-hwp'")
    conn.commit()
    assert process_once(conn, blob, today=TODAY, converter=FakeConverter(None))["ok"] == 1
    assert conn.execute("SELECT view_status FROM regulation.source_document").fetchone()["view_status"] == "failed"


def test_rebuild_all_reprocesses_from_outbox(conn, tmp_path):
    blob = LocalBlobStore(tmp_path)
    seed_alio(conn, blob, (S / "kasi-yeobi-339.pdf").read_bytes())
    process_once(conn, blob, today=TODAY)
    n_pv = conn.execute("SELECT count(*) AS n FROM regulation.provision_version").fetchone()["n"]
    assert rebuild_all(conn) == 1
    assert conn.execute("SELECT count(*) AS n FROM regulation.work").fetchone()["n"] == 0
    process_once(conn, blob, today=TODAY)
    assert conn.execute("SELECT count(*) AS n FROM regulation.provision_version").fetchone()["n"] == n_pv
    assert conn.execute("SELECT view_status FROM regulation.source_document").fetchone()["view_status"] == "not_needed"


def test_existing_view_pdf_is_reused_without_conversion(conn, tmp_path):
    blob = LocalBlobStore(tmp_path)
    seed_alio(conn, blob, (S / "nst-yeobi-18.hwp").read_bytes(), file_name="여비규정.hwp")
    conn.execute("UPDATE regulation.source_document SET mime='application/x-hwp'")
    conn.commit()
    first = FakeConverter((S / "nst-yeobi-18.view.pdf").read_bytes())
    process_once(conn, blob, today=TODAY, converter=first)
    rebuild_all(conn)
    second = FakeConverter((S / "nst-yeobi-18.view.pdf").read_bytes())
    process_once(conn, blob, today=TODAY, converter=second)
    assert first.calls == 1 and second.calls == 0
    a = conn.execute("SELECT vp.anchor FROM regulation.version_provision vp JOIN regulation.provision_version pv"
                     " ON pv.id = vp.provision_version_id WHERE pv.path = 'a9-2'").fetchone()
    assert a["anchor"]["page"] == 5
