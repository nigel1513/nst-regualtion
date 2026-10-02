from reg.graph.sync import sync_graph


def test_sync_projects_current_provisions_and_relations(loaded, neo4j_driver):
    ref = loaded.execute(
        "SELECT spv.path AS src, r.target_path AS dst, r.rel_type FROM regulation.reference r"
        " JOIN regulation.provision_version spv ON spv.id = r.source_pv_id"
        " WHERE r.resolution = 'RESOLVED' AND r.target_kind = 'PROVISION' ORDER BY r.id LIMIT 1").fetchone()
    st = sync_graph(loaded, neo4j_driver)
    assert st["works"] == 1 and st["provisions"] > 50 and st["relations"] > 5
    with neo4j_driver.session() as s:
        got = s.run(f"MATCH (a:RegProvision {{path: $src}})-[r:{ref['rel_type']}]->(b:RegProvision) RETURN b.path AS p",
                    src=ref["src"]).values()
        n = s.run("MATCH (:RegWork)-[:HAS_PROVISION]->(p) RETURN count(p) AS n").single()["n"]
    assert [ref["dst"]] in got or [ref["dst"].split(".")[0]] in got
    assert n == st["provisions"]
    assert sync_graph(loaded, neo4j_driver) == st  # 다시 해도 같다


def test_graph_lock_excludes_a_second_runner(migrated):
    import psycopg

    from reg.graph.sync import GRAPH_LOCK, graph_lock

    with psycopg.connect(migrated[0]) as a, psycopg.connect(migrated[0]) as b:
        with graph_lock(a):
            assert b.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (GRAPH_LOCK,)).fetchone()[0] is False
        assert b.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (GRAPH_LOCK,)).fetchone()[0] is True
