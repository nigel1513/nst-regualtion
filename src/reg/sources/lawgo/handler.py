"""법령 XML 판본 하나 → PreparedVersion."""
from datetime import date

from reg.core.effective import resolve
from reg.core.ingest.contract import PreparedVersion, SourceHandler
from reg.sources.lawgo.xml import parse_law_xml


def prepare(conn, blob, payload: dict, today: date, converter=None) -> PreparedVersion:
    sd = conn.execute("SELECT * FROM regulation.source_document WHERE id = %s",
                      (payload["source_document_id"],)).fetchone()
    doc = parse_law_xml(blob.get(sd["blob_key"]))
    return PreparedVersion(f"kr/law/{payload['law_id']}", doc.meta.get("kind") or "LAW", doc.title, None, sd["id"],
                           doc, resolve(doc), {"law_id": payload["law_id"], "mst": payload["mst"]})


HANDLER = SourceHandler("regulation.law_fetched", "law_id", prepare)
