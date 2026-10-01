import json
from datetime import date
from pathlib import Path

from reg.collect.archive import store
from reg.collect.sniff import FileKind
from reg.process import process_once
from reg.storage.blob import LocalBlobStore

FX = Path(__file__).parent / "fixtures"
TODAY = date(2026, 10, 2)


def seed_alio(conn, blob, content: bytes, file_name="여비규정(2024년도 1월 개정).pdf", ord_=0):
    conn.execute("INSERT INTO regulation.institution (code, name, kind, alio_apba_id, alio_name)"
                 " VALUES ('KASI','한국천문연구원','GRI','C0266','한국천문연구원') ON CONFLICT DO NOTHING")
    inst = conn.execute("SELECT id FROM regulation.institution WHERE code='KASI'").fetchone()["id"]
    conn.execute("INSERT INTO regulation.alio_rule (seq, institution_id, title, revised_on, posted_on)"
                 " VALUES ('186618', %s, '여비규정', '2024-01-17', '2016-10-17') ON CONFLICT DO NOTHING", (inst,))
    doc = store(conn, blob, source="alio", url="u", content=content, kind=FileKind("application/pdf", "pdf"),
                meta={})
    conn.execute("INSERT INTO regulation.alio_rule_file (file_no, seq, file_name, ord, status, source_document_id)"
                 " VALUES (%s,'186618',%s,%s,'fetched',%s)", (str(doc.id), file_name, ord_, doc.id))
    conn.execute("INSERT INTO regulation.outbox (topic, payload) VALUES ('regulation.source_fetched', %s)",
                 (json.dumps({"source": "alio", "source_document_id": doc.id, "institution_code": "KASI",
                              "seq": "186618", "file_no": str(doc.id), "file_name": file_name}),))
    conn.commit()


def test_alio_pdf_event_builds_current_version(conn, tmp_path):
    blob = LocalBlobStore(tmp_path)
    seed_alio(conn, blob, (FX / "samples" / "kasi-yeobi-339.pdf").read_bytes())
    st = process_once(conn, blob, today=TODAY)
    assert st == {"claimed": 1, "ok": 1, "failed": 0, "parked": 0}
    v = conn.execute("SELECT * FROM regulation.work_version").fetchone()
    assert v["work_id"] == "kr/reg/KASI/여비규정" and v["effective_from"] == date(2024, 1, 17)
    assert (v["effective_basis"], v["effective_status"], v["version_state"]) == ("supplement", "CONFIRMED", "CURRENT")
    t = conn.execute("SELECT pv.text FROM regulation.provision_version pv JOIN regulation.version_provision vp"
                     " ON vp.provision_version_id = pv.id WHERE vp.work_version_id = %s AND pv.path = 'a27.p1'",
                     (v["id"],)).fetchone()["text"]
    assert "7일 이내에" in t
    assert process_once(conn, blob, today=TODAY)["claimed"] == 0


def test_law_event(conn, tmp_path):
    blob = LocalBlobStore(tmp_path)
    doc = store(conn, blob, source="lawgo", url="u", content=(FX / "lawgo_service_283849.xml").read_bytes(),
                kind=FileKind("application/xml", "xml"), meta={})
    conn.execute("INSERT INTO regulation.outbox (topic, payload) VALUES ('regulation.law_fetched', %s)",
                 (json.dumps({"law_id": "013774", "mst": "283849", "name": "국가연구개발혁신법",
                              "source_document_id": doc.id}),))
    conn.commit()
    st = process_once(conn, blob, today=TODAY)
    err = conn.execute("SELECT last_error FROM regulation.outbox").fetchone()["last_error"]
    assert st["ok"] == 1, err
    w = conn.execute("SELECT * FROM regulation.work").fetchone()
    assert w["id"] == "kr/law/013774" and w["kind"] == "법률"
    v = conn.execute("SELECT * FROM regulation.work_version").fetchone()
    assert v["effective_from"] == date(2026, 9, 11) and v["version_state"] == "CURRENT"


def test_broken_file_fails_then_parks(conn, tmp_path):
    blob = LocalBlobStore(tmp_path)
    seed_alio(conn, blob, b"%PDF-1.4 broken")
    for _ in range(3):
        process_once(conn, blob, today=TODAY)
    ev = conn.execute("SELECT attempts, processed_at, last_error FROM regulation.outbox").fetchone()
    assert ev["attempts"] == 3 and ev["processed_at"] is None and ev["last_error"]
    assert process_once(conn, blob, today=TODAY)["claimed"] == 0


def test_review_each_event_commits_independently(conn, tmp_path, monkeypatch):
    import psycopg

    from reg import process as P

    blob = LocalBlobStore(tmp_path)
    seed_alio(conn, blob, (FX / "samples" / "kasi-yeobi-339.pdf").read_bytes())
    conn.execute("INSERT INTO regulation.outbox (topic, payload) VALUES ('regulation.law_fetched', '{}')")
    conn.commit()
    real = P.HANDLERS["regulation.law_fetched"]

    def boom(*a, **k):
        raise KeyboardInterrupt
    monkeypatch.setitem(P.HANDLERS, "regulation.law_fetched", boom)
    import pytest
    with pytest.raises(KeyboardInterrupt):
        process_once(conn, blob, today=TODAY)
    conn.rollback()
    other = psycopg.connect(conn.info.dsn + " password=app")
    n = other.execute("SELECT count(*) FROM regulation.outbox WHERE processed_at IS NOT NULL").fetchone()[0]
    other.close()
    monkeypatch.setitem(P.HANDLERS, "regulation.law_fetched", real)
    assert n == 1


def test_events_of_one_work_are_rebuilt_once(conn, tmp_path, monkeypatch):
    from reg import process as P

    blob = LocalBlobStore(tmp_path)
    seed_alio(conn, blob, (FX / "samples" / "kasi-yeobi-339.pdf").read_bytes(), ord_=1)
    seed_alio(conn, blob, (FX / "samples" / "kasi-yeobi-339.pdf").read_bytes()[:-10] + b"%%EOF\n" + b" " * 10,
              file_name="여비규정(2023년도 4월 개정).pdf", ord_=0)
    calls = []
    real = P.rebuild_work
    monkeypatch.setattr(P, "rebuild_work", lambda c, w, t: calls.append(w) or real(c, w, t))
    st = process_once(conn, blob, today=TODAY)
    assert st["claimed"] == 2 and st["ok"] == 2 and calls == ["kr/reg/KASI/여비규정"]


def test_document_without_readable_articles_goes_to_review_queue(conn, tmp_path, monkeypatch):
    from reg import process as P
    from reg.structure.model import Block

    blob = LocalBlobStore(tmp_path)
    seed_alio(conn, blob, (FX / "samples" / "kasi-yeobi-339.pdf").read_bytes())
    # 글꼴 숫자 인코딩이 깨진 PDF처럼: 텍스트는 있지만 조 번호가 사라진 상태
    monkeypatch.setattr(P, "extract", lambda data, mime, name: [Block("연구수당지급기준"), Block("제 조 (목적) 이 기준은")])
    st = process_once(conn, blob, today=TODAY)
    assert st["ok"] == 1 and st["failed"] == 0
    t = conn.execute("SELECT kind, target, detail FROM regulation.review_task").fetchone()
    assert t["kind"] == "LOW_TEXT" and t["target"].startswith("source:") and "조문" in t["detail"]["reason"]
    assert conn.execute("SELECT count(*) AS n FROM regulation.work").fetchone()["n"] == 0
