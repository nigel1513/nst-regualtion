"""승격 (spec §3A.4, D-10): 내부규정이 인용한 법령·행정규칙 + 설정 지정분만 regulation.work로.

현행 판본이 아직 work_version에 없으면 outbox regulation.law_fetched {law_id, mst, source_document_id}를 남긴다.
처리 전인 같은 MST 이벤트가 있으면 다시 내지 않는다. 처리 뒤에는 work.law_id, work_version.law_mst를 잇는다.
"""
from reg.platform import outbox
from reg.sources.lawgo.config import LawgoConfig
from reg.sources.lawgo.handler import TOPIC
from reg.sources.lawgo.ids import work_id_for
from reg.sources.lawgo.link import resolve_name


def promote_targets(conn, cfg: LawgoConfig) -> tuple[set[str], list[str]]:
    ids = {r["target_law_id"] for r in conn.execute(
        "SELECT DISTINCT target_law_id FROM regulation.reference WHERE target_law_id IS NOT NULL").fetchall()}
    missing = []
    for name in cfg.promote_laws + cfg.promote_admruls:
        hit = resolve_name(conn, name)
        if len(hit) == 1:
            ids.add(hit[0])
        else:
            missing.append(name)
    return ids, missing


def promote_all(conn, cfg: LawgoConfig) -> dict:
    ids, missing = promote_targets(conn, cfg)
    st = {"targets": len(ids), "emitted": 0, "up_to_date": 0, "pending": 0, "missing_config": missing,
          "works_linked": 0, "versions_linked": 0}
    rows = conn.execute(
        "SELECT v.mst, v.law_id, v.source_document_id FROM law.law_version v JOIN law.law_master m ON m.law_id = v.law_id"
        " WHERE v.is_current AND v.articles_loaded AND v.source_document_id IS NOT NULL AND m.status = '현행'"
        " AND v.law_id = ANY(%s) ORDER BY v.law_id", (sorted(ids),)).fetchall()
    for r in rows:
        if conn.execute("SELECT 1 FROM regulation.work_version WHERE work_id = %s AND source_document_id = %s",
                        (work_id_for(r["law_id"]), r["source_document_id"])).fetchone():
            st["up_to_date"] += 1
        elif conn.execute("SELECT 1 FROM ops.outbox WHERE topic = %s AND processed_at IS NULL AND payload->>'mst' = %s",
                          (TOPIC, r["mst"])).fetchone():
            st["pending"] += 1
        else:
            outbox.write(conn, TOPIC, {"law_id": r["law_id"], "mst": r["mst"],
                                       "source_document_id": r["source_document_id"]})
            st["emitted"] += 1
    st["works_linked"] = conn.execute(
        "UPDATE regulation.work w SET law_id = m.law_id FROM law.law_master m"
        " WHERE w.id = CASE WHEN m.family = 'law' THEN 'kr/law/' || m.law_id ELSE 'kr/admrul/' || m.source_id END"
        " AND w.law_id IS DISTINCT FROM m.law_id").rowcount
    st["versions_linked"] = conn.execute(
        "UPDATE regulation.work_version wv SET law_mst = v.mst FROM law.law_version v"
        " WHERE wv.source_document_id = v.source_document_id AND wv.law_mst IS DISTINCT FROM v.mst").rowcount
    conn.commit()
    return st
