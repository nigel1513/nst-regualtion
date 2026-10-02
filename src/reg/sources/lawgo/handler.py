"""regulation.law_fetched 처리기: 미러 판본(XML은 SeaweedFS 보관 원본) → PreparedVersion. 적재는 core가 한다."""
from datetime import date

from reg.core.effective import resolve
from reg.core.ingest.contract import PreparedVersion, SourceHandler
from reg.sources.lawgo.ids import work_id_for
from reg.sources.lawgo.xml import parse_admrul_xml, parse_law_xml

TOPIC = "regulation.law_fetched"


def prepare(conn, blob, payload: dict, today: date, converter=None) -> PreparedVersion:
    sd = conn.execute("SELECT id, blob_key FROM regulation.source_document WHERE id = %s",
                      (payload["source_document_id"],)).fetchone()
    if sd is None:
        raise LookupError(f"source_document {payload['source_document_id']} 없음")
    m = conn.execute("SELECT family, kind FROM law.law_master WHERE law_id = %s", (payload["law_id"],)).fetchone()
    family = m["family"] if m else "law"  # 미러 이전의 구 law_sync 이벤트 (판정 R11)
    data = blob.get(sd["blob_key"])
    doc = parse_admrul_xml(data) if family == "admrul" else parse_law_xml(data)
    kind = (m["kind"] if m else None) or doc.meta.get("kind") or "LAW"
    return PreparedVersion(work_id_for(payload["law_id"]), kind, doc.title, None, sd["id"], doc, resolve(doc),
                           {"law_id": payload["law_id"], "mst": payload["mst"]})


HANDLER = SourceHandler(TOPIC, "law_id", prepare)
