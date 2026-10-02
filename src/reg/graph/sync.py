"""PostgreSQL(기준) → Neo4j 법령·규정 구조 그래프 (spec 2026-10-03 §1.2).

- 전체 재투영 `rebuild`: 그래프를 비우고 모든 규범문서·dated 판본을 UNWIND 배치(5,000)로 넣는다.
- 규범문서 단위 증분 `sync_works`: 그 Work의 하위 그래프를 지우고 다시 넣는다. 그 문서에서 나가는 참조와
  다른 문서에서 그 문서로 들어오는 참조를 함께 다시 잇는다(재적재로 조항 판본 id가 바뀌므로).
- `sync_changed`: Work 노드의 지문(fp)이 PostgreSQL과 다른 문서만 증분한다. 그래프가 비었으면 전체 재투영."""
from contextlib import contextmanager

from reg.graph.project import all_work_ids, fingerprints, reference_batches, work_batches

BATCH = 5000
GRAPH_LOCK = "regulation.graph"
LABELS = ("Institution", "Work", "Version", "Provision", "Term", "MissingProvision", "GraphSync")

SCHEMA = [
    "CREATE CONSTRAINT provision_pv IF NOT EXISTS FOR (p:Provision) REQUIRE p.pv_id IS UNIQUE",
    "CREATE CONSTRAINT version_id IF NOT EXISTS FOR (v:Version) REQUIRE v.id IS UNIQUE",
    "CREATE CONSTRAINT work_id IF NOT EXISTS FOR (w:Work) REQUIRE w.id IS UNIQUE",
    "CREATE CONSTRAINT institution_code IF NOT EXISTS FOR (i:Institution) REQUIRE i.code IS UNIQUE",
    "CREATE CONSTRAINT term_key IF NOT EXISTS FOR (t:Term) REQUIRE t.key IS UNIQUE",
    "CREATE CONSTRAINT missing_key IF NOT EXISTS FOR (m:MissingProvision) REQUIRE m.key IS UNIQUE",
    "CREATE INDEX provision_path IF NOT EXISTS FOR (p:Provision) ON (p.path)",
    "CREATE INDEX provision_full_label IF NOT EXISTS FOR (p:Provision) ON (p.full_label)",
    "CREATE INDEX provision_work IF NOT EXISTS FOR (p:Provision) ON (p.work_id)",
    "CREATE INDEX provision_lineage IF NOT EXISTS FOR (p:Provision) ON (p.lineage)",
    "CREATE INDEX version_work IF NOT EXISTS FOR (v:Version) ON (v.work_id)",
    "CREATE INDEX term_work IF NOT EXISTS FOR (t:Term) ON (t.work_id)",
    "CREATE INDEX missing_work IF NOT EXISTS FOR (m:MissingProvision) ON (m.work_id)",
    "CREATE FULLTEXT INDEX term_name IF NOT EXISTS FOR (t:Term) ON EACH [t.name]"
    " OPTIONS {indexConfig: {`fulltext.analyzer`: 'cjk'}}",
]
# 옛 보조 그래프(Reg* 라벨) 제약 — 재투영 때 걷어낸다
LEGACY = ["DROP CONSTRAINT reg_prov_key IF EXISTS", "DROP CONSTRAINT reg_work_id IF EXISTS",
          "DROP CONSTRAINT reg_inst_code IF EXISTS", "DROP INDEX reg_prov_work IF EXISTS"]
REF_TARGET = {"prov": "MATCH (b:Provision {pv_id: r.dst})", "work": "MATCH (b:Work {id: r.dst})",
              "missing": "MERGE (b:MissingProvision {key: r.dst}) ON CREATE SET b.work_id = r.work_id, b.path = r.path"}


@contextmanager
def graph_lock(conn):
    """재투영·증분은 하위 그래프를 지웠다 다시 만든다. 그 사이 다른 실행의 영향 분석이 빈 그래프를 읽지 않도록
    투영과 분석(scan·backtest)을 한 세션 잠금 안에서 한다."""
    conn.execute("SELECT pg_advisory_lock(hashtext(%s))", (GRAPH_LOCK,))
    try:
        yield
    finally:
        conn.execute("SELECT pg_advisory_unlock(hashtext(%s))", (GRAPH_LOCK,))


def ensure_schema(driver) -> None:
    with driver.session() as s:
        for q in SCHEMA:
            s.run(q).consume()


def _write(s, query: str, rows: list) -> int:
    for i in range(0, len(rows), BATCH):
        s.run(query, rows=rows[i:i + BATCH]).consume()
    return len(rows)


def _delete_loop(s, match: str, **kw) -> None:
    while s.run(f"{match} WITH n LIMIT 10000 DETACH DELETE n RETURN count(*) AS c", **kw).single()["c"]:
        pass


def _write_works(s, conn, ids: list[str]) -> dict:
    st = dict.fromkeys(("works", "versions", "provisions", "contains", "changes", "terms", "uses"), 0)
    for rows in work_batches(conn, ids):
        _write(s, "UNWIND $rows AS r MERGE (i:Institution {code: r.code}) SET i.name = r.name, i.aliases = r.aliases",
               rows.institutions)
        st["works"] += _write(s, "UNWIND $rows AS r CREATE (w:Work {id: r.id}) SET w += r.props"
                                 " WITH w, r WHERE r.institution IS NOT NULL MATCH (i:Institution {code: r.institution})"
                                 " CREATE (i)-[:ISSUES]->(w)", rows.works)
        st["versions"] += _write(s, "UNWIND $rows AS r MATCH (w:Work {id: r.work_id}) CREATE (v:Version {id: r.id})"
                                    " SET v += r.props CREATE (w)-[:HAS_VERSION]->(v)", rows.versions)
        _write(s, "UNWIND $rows AS r MATCH (a:Version {id: r.a}), (b:Version {id: r.b}) CREATE (a)-[:NEXT_VERSION]->(b)",
               rows.next_versions)
        for label, prows in rows.provisions.items():
            extra = f":{label}" if label else ""
            st["provisions"] += _write(s, f"UNWIND $rows AS r CREATE (p:Provision{extra} {{pv_id: r.pv_id}})"
                                          " SET p += r.props", prows)
        st["contains"] += _write(s, "UNWIND $rows AS r MATCH (v:Version {id: r.vid}), (p:Provision {pv_id: r.pv})"
                                    " CREATE (v)-[:CONTAINS {ord: r.ord}]->(p)", rows.top)
        st["contains"] += _write(s, "UNWIND $rows AS r MATCH (a:Provision {pv_id: r.a}), (b:Provision {pv_id: r.b})"
                                    " CREATE (a)-[:CONTAINS {ord: r.ord, versions: r.versions}]->(b)", rows.contains)
        st["changes"] += _write(s, "UNWIND $rows AS r MATCH (a:Provision {pv_id: r.a}), (b:Provision {pv_id: r.b})"
                                   " CREATE (a)-[x:AMENDED_TO]->(b) SET x = r.props", rows.amended)
        for rel, part in (("ADDED_IN", rows.added), ("DELETED_IN", rows.deleted)):
            st["changes"] += _write(s, f"UNWIND $rows AS r MATCH (p:Provision {{pv_id: r.pv}}), (v:Version {{id: r.vid}})"
                                       f" CREATE (p)-[:{rel}]->(v)", part)
        st["terms"] += _write(s, "UNWIND $rows AS r CREATE (t:Term {key: r.key}) SET t += r.props", rows.terms)
        _write(s, "UNWIND $rows AS r MATCH (p:Provision {pv_id: r.pv}), (t:Term {key: r.key}) CREATE (p)-[:DEFINES]->(t)",
               rows.defines)
        st["uses"] += _write(s, "UNWIND $rows AS r MATCH (p:Provision {pv_id: r.pv}), (t:Term {key: r.key})"
                                " CREATE (p)-[:USES]->(t)", rows.uses)
    return st


def _write_references(s, conn, ids: list[str] | None) -> int:
    n = 0
    for rows in reference_batches(conn, ids):
        groups: dict[tuple, list] = {}
        for r in rows:
            groups.setdefault((r["rel"], r["kind"]), []).append(r)
        for (rel, kind), part in groups.items():
            for i in range(0, len(part), BATCH):
                res = s.run(f"UNWIND $rows AS r MATCH (a:Provision {{pv_id: r.src}}) {REF_TARGET[kind]}"
                            f" CREATE (a)-[x:{rel}]->(b) SET x = r.props", rows=part[i:i + BATCH]).consume()
                n += res.counters.relationships_created
    return n


def _mark(s, mode: str, n: int) -> None:
    s.run("MERGE (g:GraphSync {id: 'graph'}) SET g.synced_at = datetime(), g.mode = $mode, g.works = $n",
          mode=mode, n=n).consume()


def rebuild(conn, driver) -> dict:
    """전체 재투영. 통계는 같은 입력이면 같다."""
    with driver.session() as s:
        for q in LEGACY:
            s.run(q).consume()
        _delete_loop(s, "MATCH (n) WHERE any(l IN labels(n) WHERE l IN $labels OR l STARTS WITH 'Reg')",
                     labels=list(LABELS))
    ensure_schema(driver)
    with driver.session() as s:
        st = _write_works(s, conn, all_work_ids(conn))
        st["relations"] = _write_references(s, conn, None)
        _mark(s, "rebuild", st["works"])
    return st


sync_graph = rebuild  # 옛 이름 (alerts 테스트·호출부 호환)


def sync_works(conn, driver, work_ids: list[str]) -> dict:
    """규범문서 단위 증분: 하위 그래프를 지우고 다시 넣는다. PostgreSQL에 없는 문서는 지우기만 한다."""
    ids = sorted(set(work_ids))
    ensure_schema(driver)
    with driver.session() as s:
        for label in ("Provision", "Version", "Term", "MissingProvision"):
            _delete_loop(s, f"MATCH (n:{label}) WHERE n.work_id IN $ids", ids=ids)
        _delete_loop(s, "MATCH (n:Work) WHERE n.id IN $ids", ids=ids)
        present = [r["id"] for r in conn.execute("SELECT id FROM regulation.work WHERE id = ANY(%s)",
                                                 (ids,)).fetchall()]
        st = _write_works(s, conn, sorted(present))
        st["relations"] = _write_references(s, conn, ids)
        s.run("MATCH (m:MissingProvision) WHERE NOT (m)--() DELETE m").consume()
        st["removed"] = len(ids) - len(present)
        st["works"] = len(ids)
    return st


def sync_changed(conn, driver) -> dict:
    """지문이 바뀐(또는 새로 생기거나 사라진) 규범문서만 증분. 그래프가 비었으면 전체 재투영."""
    with driver.session() as s:
        graph = {r["id"]: r["fp"] for r in s.run("MATCH (w:Work) RETURN w.id AS id, w.fp AS fp")}
    if not graph:
        return {"mode": "rebuild", **rebuild(conn, driver)}
    pg = fingerprints(conn)
    changed = sorted({w for w, fp in pg.items() if graph.get(w) != fp} | (set(graph) - set(pg)))
    if not changed:
        return {"mode": "incremental", "works": 0}
    st = sync_works(conn, driver, changed)
    with driver.session() as s:
        _mark(s, "incremental", len(changed))
    return {"mode": "incremental", **st, "changed": changed[:50]}


def graph_stats(driver) -> dict:
    qs = {"works": "MATCH (n:Work) RETURN count(n) AS n", "versions": "MATCH (n:Version) RETURN count(n) AS n",
          "provisions": "MATCH (n:Provision) RETURN count(n) AS n", "terms": "MATCH (n:Term) RETURN count(n) AS n",
          "relations": "MATCH (:Provision)-[r:BASIS|DELEGATION|IMPLEMENTS|MUTATIS|EXCEPTION|CITATION]->()"
                       " RETURN count(r) AS n"}
    with driver.session() as s:
        return {k: s.run(q).single()["n"] for k, q in qs.items()}
