from reg import outbox
from reg.collect.archive import store
from reg.collect.lawgo import LawGoClient, norm_name
from reg.collect.sniff import FileKind
from reg.storage.blob import BlobStore

XML = FileKind("application/xml", "xml")
SERVICE_URL = "https://www.law.go.kr/DRF/lawService.do?target=law&type=XML&MST={}"


def sync_laws(conn, client: LawGoClient, blob: BlobStore, names: list[str]) -> dict:
    st = {"checked": 0, "fetched": 0, "not_found": []}
    for name in names:
        st["checked"] += 1
        hit = next((r for r in client.search(name)
                    if norm_name(r.name) == norm_name(name) and r.status == "현행"), None)
        if hit is None:
            st["not_found"].append(name)
            continue
        w = conn.execute("SELECT last_mst FROM regulation.law_watch WHERE law_id = %s", (hit.law_id,)).fetchone()
        if w and w["last_mst"] == hit.mst:
            conn.execute("UPDATE regulation.law_watch SET last_checked_at = now() WHERE law_id = %s", (hit.law_id,))
            conn.commit()
            continue
        doc = store(conn, blob, source="lawgo", url=SERVICE_URL.format(hit.mst), content=client.fetch(hit.mst),
                    kind=XML, meta={"law_id": hit.law_id, "mst": hit.mst, "name": hit.name})
        conn.execute(
            "INSERT INTO regulation.law_watch (law_id, name, kind, last_mst, promulgated_on, effective_on,"
            " source_document_id, last_checked_at) VALUES (%s,%s,%s,%s,%s,%s,%s, now())"
            " ON CONFLICT (law_id) DO UPDATE SET name = EXCLUDED.name, kind = EXCLUDED.kind,"
            " last_mst = EXCLUDED.last_mst, promulgated_on = EXCLUDED.promulgated_on,"
            " effective_on = EXCLUDED.effective_on, source_document_id = EXCLUDED.source_document_id,"
            " last_checked_at = now()",
            (hit.law_id, hit.name, hit.kind, hit.mst, hit.promulgated_on, hit.effective_on, doc.id))
        if doc.is_new:
            outbox.write(conn, "regulation.law_fetched",
                         {"law_id": hit.law_id, "mst": hit.mst, "name": hit.name, "source_document_id": doc.id})
        st["fetched"] += 1
        conn.commit()
    return st
