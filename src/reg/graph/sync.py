"""PostgreSQL(기준) → Neo4j(파생) 전체 재투영. 현행 버전만, Reg* 라벨만 다룬다 (spec 5.5, D-05)."""
from contextlib import contextmanager

RELS = ("BASIS", "DELEGATION", "IMPLEMENTS", "MUTATIS", "EXCEPTION", "CITATION")
UNITS = ("article", "paragraph", "item", "subitem", "supplement", "supp_article", "annex")
BATCH = 2000
GRAPH_LOCK = "regulation.graph"


@contextmanager
def graph_lock(conn):
    """재투영은 그래프를 지웠다 다시 만든다. 그 사이 다른 실행의 영향 분석이 빈 그래프를 읽지 않도록
    재투영과 분석(scan·backtest)을 한 세션 잠금 안에서 한다."""
    conn.execute("SELECT pg_advisory_lock(hashtext(%s))", (GRAPH_LOCK,))
    try:
        yield
    finally:
        conn.execute("SELECT pg_advisory_unlock(hashtext(%s))", (GRAPH_LOCK,))


def _chunks(rows: list, n: int = BATCH):
    for i in range(0, len(rows), n):
        yield rows[i:i + n]


def sync_graph(conn, driver) -> dict:
    works = conn.execute(
        "SELECT w.id AS work_id, w.title, w.kind, i.code AS institution, i.name AS inst_name, v.id AS version_id"
        " FROM regulation.work w JOIN regulation.work_version v ON v.work_id = w.id AND v.version_state = 'CURRENT'"
        " LEFT JOIN regulation.institution i ON i.id = w.institution_id").fetchall()
    provs = conn.execute(
        "SELECT v.work_id, pv.path, pv.number_label AS label, pv.heading FROM regulation.work_version v"
        " JOIN regulation.version_provision vp ON vp.work_version_id = v.id"
        " JOIN regulation.provision_version pv ON pv.id = vp.provision_version_id"
        " WHERE v.version_state = 'CURRENT' AND pv.unit = ANY(%s)", (list(UNITS),)).fetchall()
    rels = conn.execute(
        "SELECT r.work_id, spv.path AS source_path, r.rel_type, r.target_kind, r.target_work_id, r.target_path,"
        " r.evidence_text AS evidence, r.resolution, r.review_status FROM regulation.reference r"
        " JOIN regulation.provision_version spv ON spv.id = r.source_pv_id"
        " JOIN regulation.version_provision vp ON vp.provision_version_id = spv.id"
        " JOIN regulation.work_version v ON v.id = vp.work_version_id AND v.version_state = 'CURRENT'"
        " WHERE r.resolution = 'RESOLVED' AND r.target_work_id IS NOT NULL"
        " AND r.target_kind IN ('PROVISION', 'WORK')").fetchall()
    keys = {f"{p['work_id']}|{p['path']}" for p in provs}
    current = {w["work_id"] for w in works}
    by_type: dict[tuple[str, str], dict[tuple, dict]] = {}
    for r in rels:
        src = f"{r['work_id']}|{r['source_path']}"
        if r["rel_type"] not in RELS or r["target_work_id"] not in current or src not in keys:
            continue
        if r["target_kind"] == "WORK" or not r["target_path"]:
            kind, dst = "work", r["target_work_id"]
        else:  # 대상 조항이 현행에 없으면(항·호 번호 변경) 그 조에 잇는다
            dst, kind = f"{r['target_work_id']}|{r['target_path']}", "prov"
            if dst not in keys:
                dst = f"{r['target_work_id']}|{r['target_path'].split('.')[0]}"
            if dst not in keys:  # 현행에서 삭제된 조항: 개정 영향(삭제) 탐색을 위해 missing 노드로 남긴다
                dst, kind = f"{r['target_work_id']}|{r['target_path']}", "missing"
        row = {"src": src, "dst": dst, "evidence": r["evidence"] or "", "source_path": r["source_path"],
               "resolution": r["resolution"], "review_status": r["review_status"]}
        by_type.setdefault((r["rel_type"], kind), {})[(src, dst, row["evidence"])] = row
    n_rel = 0
    with driver.session() as s:
        while s.run("MATCH (n) WHERE any(l IN labels(n) WHERE l STARTS WITH 'Reg') WITH n LIMIT 10000"
                    " DETACH DELETE n RETURN count(n) AS c").single()["c"]:
            pass
        s.run("CREATE CONSTRAINT reg_prov_key IF NOT EXISTS FOR (p:RegProvision) REQUIRE p.key IS UNIQUE")
        s.run("CREATE CONSTRAINT reg_work_id IF NOT EXISTS FOR (w:RegWork) REQUIRE w.work_id IS UNIQUE")
        s.run("CREATE INDEX reg_prov_work IF NOT EXISTS FOR (p:RegProvision) ON (p.work_id)")
        s.run("CREATE CONSTRAINT reg_inst_code IF NOT EXISTS FOR (i:RegInstitution) REQUIRE i.code IS UNIQUE")
        for part in _chunks([dict(w) for w in works]):
            s.run("UNWIND $rows AS r MERGE (w:RegWork {work_id: r.work_id})"
                  " SET w.title = r.title, w.kind = r.kind, w.institution = r.institution, w.version_id = r.version_id"
                  " WITH w, r WHERE r.institution IS NOT NULL"
                  " MERGE (i:RegInstitution {code: r.institution}) SET i.name = r.inst_name MERGE (i)-[:ISSUES]->(w)",
                  rows=part)
        for part in _chunks([{**dict(p), "key": f"{p['work_id']}|{p['path']}"} for p in provs]):
            s.run("UNWIND $rows AS r MATCH (w:RegWork {work_id: r.work_id})"
                  " MERGE (p:RegProvision {key: r.key}) SET p.work_id = r.work_id, p.path = r.path, p.label = r.label,"
                  " p.heading = r.heading MERGE (w)-[:HAS_PROVISION]->(p)", rows=part)
        missing = {row["dst"] for (_, kind), rows in by_type.items() if kind == "missing" for row in rows.values()}
        for part in _chunks([{"key": k, "work_id": k.split("|")[0], "path": k.split("|")[1]} for k in sorted(missing)]):
            s.run("UNWIND $rows AS r MERGE (p:RegProvision {key: r.key})"
                  " SET p.work_id = r.work_id, p.path = r.path, p.missing = true", rows=part)
        for (rel, kind), rows in by_type.items():
            target = "MATCH (b:RegWork {work_id: r.dst})" if kind == "work" else "MATCH (b:RegProvision {key: r.dst})"
            for part in _chunks(list(rows.values())):
                s.run(f"UNWIND $rows AS r MATCH (a:RegProvision {{key: r.src}}) {target}"
                      f" MERGE (a)-[x:{rel} {{source_path: r.source_path, evidence: r.evidence}}]->(b)"
                      " SET x.resolution = r.resolution, x.review_status = r.review_status", rows=part)
                n_rel += len(part)
    return {"works": len(works), "provisions": len(provs), "relations": n_rel}
