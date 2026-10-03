from datetime import date

from reg.core.ingest.loader import rebuild_work, upsert_work
from reg.core.model import Prov
from reg.core.refs import resolve_and_store
from reg.graph.sync import graph_stats, rebuild, sync_changed, sync_graph, sync_works
from reg.platform.storage.blob import LocalBlobStore
from tests.test_impact import T, _ver, setup

LAW_V2 = [Prov("a5", "article", "제5조", "정산", "정산은 10일 이내에 한다.")]  # 제5조 개정, 제6조 삭제

TRAVEL = [Prov("a1", "article", "제1조", "목적", "이 규정은 출장에 관한 사항을 정한다."),
          Prov("a2", "article", "제2조", "정의", "이 규정에서 사용하는 용어의 뜻은 다음과 같다."),
          Prov("a2.i1", "item", "1.", None, '"출장"이란 공무로 근무지 밖에 가는 것을 말한다.', "a2"),
          Prov("a2.i2", "item", "2.", None, '"여비"란 운임·일비·숙박비 및 식비를 말한다.', "a2"),
          Prov("a2.i3", "item", "3.", None, '"일비"란 출장 중 현지 교통비 등을 말한다.', "a2"),
          Prov("a2.i4", "item", "4.", None, '"숙박비"란 출장 중 숙박에 드는 비용을 말한다.', "a2"),
          Prov("a2.i5", "item", "5.", None, '"출장자"란 출장 명령을 받은 직원을 말한다.', "a2"),
          Prov("c2", "chapter", "제2장", "여비", ""),
          Prov("a3", "article", "제3조", "여비의 청구", "", "c2"),
          Prov("a3.p1", "paragraph", "①", None, "출장자는 여비를 청구할 수 있다.", "a3"),
          Prov("a3.p2", "paragraph", "②", None, "일비는 출장 일수에 따라 지급한다.", "a3"),
          Prov("a4", "article", "제4조", "숙박", "숙박비는 실비로 지급한다.", "c2"),
          Prov("a5", "article", "제5조", "특례", "제3조에도 불구하고 국외 출장은 따로 정한다.", "c2")]


def build(conn, tmp_path):
    """가상 법(v1 2020 · v2 2026: 제5조 개정·제6조 삭제) + 그것을 인용하는 여비규정 + 정의 조를 가진 출장규정."""
    vid = setup(conn, tmp_path, LAW_V2)
    blob = LocalBlobStore(tmp_path)
    inst = conn.execute("SELECT id FROM regulation.institution WHERE code = 'KASI'").fetchone()["id"]
    upsert_work(conn, "kr/reg/KASI/출장", "INTERNAL_REG", "출장규정", inst, {})
    _ver(conn, blob, "kr/reg/KASI/출장", "출장규정", TRAVEL, date(2022, 1, 1), b"T1")
    rebuild_work(conn, "kr/reg/KASI/출장", T)
    resolve_and_store(conn, "kr/reg/KASI/출장")
    conn.commit()
    return vid


def pv(conn, work, path, eff=None):
    q = ("SELECT pv.id FROM regulation.provision_version pv JOIN regulation.version_provision vp"
         " ON vp.provision_version_id = pv.id JOIN regulation.work_version v ON v.id = vp.work_version_id"
         " WHERE v.work_id = %s AND pv.path = %s" + (" AND v.effective_from = %s" if eff else
                                                     " AND v.version_state = 'CURRENT'"))
    return conn.execute(q, (work, path, eff) if eff else (work, path)).fetchone()["id"]


def one(driver, q, **kw):
    with driver.session() as s:
        return s.run(q, **kw).data()


def test_rebuild_projects_versions_hierarchy_lineage_and_dated_references(conn, tmp_path, neo4j_driver):
    vid = build(conn, tmp_path)
    st = rebuild(conn, neo4j_driver)
    assert st["works"] == 3 and st["versions"] == 4 and st["terms"] == 5
    assert graph_stats(neo4j_driver)["provisions"] == st["provisions"]
    assert one(neo4j_driver, "MATCH (:Work {id: 'kr/law/L1'})-[:HAS_VERSION]->(a:Version)-[:NEXT_VERSION]->(b:Version)"
                             " RETURN a.effective_from AS a, b.id AS b, b.state AS s") == \
        [{"a": "2020-01-01", "b": vid, "s": "CURRENT"}]
    a5v1, a5v2 = pv(conn, "kr/law/L1", "a5", date(2020, 1, 1)), pv(conn, "kr/law/L1", "a5")
    assert one(neo4j_driver, "MATCH (a:Provision {pv_id: $a})-[r:AMENDED_TO]->(b:Provision {pv_id: $b})"
                             " RETURN r.kind AS k, a.lineage = b.lineage AS same, a.valid_to AS to, b.current AS cur",
               a=a5v1, b=a5v2) == [{"k": "MODIFIED", "same": True, "to": "2026-01-01", "cur": True}]
    assert one(neo4j_driver, "MATCH (p:Provision:Article {pv_id: $p})-[:DELETED_IN]->(v:Version) RETURN v.id AS v",
               p=pv(conn, "kr/law/L1", "a6", date(2020, 1, 1))) == [{"v": vid}]
    # 여비규정(2021 시행)의 제3조는 2021년에 유효했던 법 v1의 제5조를 가리킨다
    got = one(neo4j_driver, "MATCH (a:Provision {pv_id: $a})-[r]->(b:Provision) RETURN type(r) AS t, b.pv_id AS b,"
                            " r.match AS m, a.full_label AS fl", a=pv(conn, "kr/reg/KASI/여비", "a3"))
    assert got == [{"t": "BASIS", "b": a5v1, "m": "as_of", "fl": "여비규정 제3조"}]
    assert one(neo4j_driver, "MATCH (a:Provision {path: 'a8', work_id: 'kr/reg/KASI/여비'})-[r]->(w:Work)"
                             " RETURN type(r) AS t, w.id AS w") == [{"t": "CITATION", "w": "kr/law/L1"}]
    assert one(neo4j_driver, "MATCH (a:Provision {path: 'a7', work_id: 'kr/reg/KASI/여비'})-[r:EXCEPTION]->(b)"
                             " RETURN b.path AS p") == [{"p": "a3"}]
    assert one(neo4j_driver, "MATCH (:Institution {code: 'KASI'})-[:ISSUES]->(w:Work) RETURN w.id AS w ORDER BY w") == \
        [{"w": "kr/reg/KASI/여비"}, {"w": "kr/reg/KASI/출장"}]


def test_hierarchy_full_labels_and_terms(conn, tmp_path, neo4j_driver):
    build(conn, tmp_path)
    rebuild(conn, neo4j_driver)
    w = "kr/reg/KASI/출장"
    assert one(neo4j_driver, "MATCH (v:Version {work_id: $w})-[r:CONTAINS]->(p) RETURN p.path AS p ORDER BY r.ord",
               w=w) == [{"p": "a1"}, {"p": "a2"}, {"p": "c2"}]
    assert one(neo4j_driver, "MATCH (c:Chapter {work_id: $w})-[:CONTAINS]->(a:Article)-[r:CONTAINS]->(p:Paragraph)"
                             " RETURN a.path AS a, p.full_label AS fl, size(r.versions) AS n ORDER BY r.ord", w=w) == \
        [{"a": "a3", "fl": "출장규정 제3조 제1항", "n": 1}, {"a": "a3", "fl": "출장규정 제3조 제2항", "n": 1}]
    assert one(neo4j_driver, "MATCH (d:Item)-[:DEFINES]->(t:Term {name: '여비'}) RETURN d.path AS d, t.key AS k,"
                             " t.definition AS df") == \
        [{"d": "a2.i2", "k": f"{w}|여비", "df": '"여비"란 운임·일비·숙박비 및 식비를 말한다'}]
    uses = one(neo4j_driver, "MATCH (p:Provision {path: 'a3.p1'})-[:USES]->(t:Term) RETURN t.name AS n ORDER BY n")
    assert uses == [{"n": "여비"}, {"n": "출장"}, {"n": "출장자"}]
    assert one(neo4j_driver, "MATCH (p:Provision {path: 'a2.i2'})-[:USES]->(t:Term {name: '여비'}) RETURN p") == []
    assert one(neo4j_driver, "MATCH (c:Chapter)-[:USES]->() RETURN c") == []  # 장·절은 용어를 쓰지 않는다
    with neo4j_driver.session() as s:
        hits = s.run("CALL db.index.fulltext.queryNodes('term_name', '숙박비') YIELD node RETURN node.name AS n").values()
    assert ["숙박비"] in hits


def test_sync_works_relinks_incoming_references_after_target_reload(conn, tmp_path, neo4j_driver):
    build(conn, tmp_path)
    rebuild(conn, neo4j_driver)
    assert sync_changed(conn, neo4j_driver)["works"] == 0
    rebuild_work(conn, "kr/law/L1", T)  # 법만 다시 적재 → 조항 판본 id가 모두 바뀐다
    conn.commit()
    st = sync_changed(conn, neo4j_driver)
    assert st["mode"] == "incremental" and st["works"] == 1
    a5v1 = pv(conn, "kr/law/L1", "a5", date(2020, 1, 1))
    assert one(neo4j_driver, "MATCH (a:Provision {path: 'a3', work_id: 'kr/reg/KASI/여비'})-[:BASIS]->(b)"
                             " RETURN b.pv_id AS b") == [{"b": a5v1}]
    assert one(neo4j_driver, "MATCH (p:Provision {work_id: 'kr/law/L1'}) RETURN count(p) AS n")[0]["n"] == \
        conn.execute("SELECT count(DISTINCT vp.provision_version_id) AS n FROM regulation.version_provision vp"
                     " JOIN regulation.work_version v ON v.id = vp.work_version_id WHERE v.work_id = 'kr/law/L1'"
                     " AND v.effective_from IS NOT NULL").fetchone()["n"]
    assert sync_changed(conn, neo4j_driver)["works"] == 0
    assert sync_works(conn, neo4j_driver, ["kr/reg/KASI/여비"])["works"] == 1  # 지정 재적재도 같은 결과
    assert one(neo4j_driver, "MATCH (:Provision {path: 'a3', work_id: 'kr/reg/KASI/여비'})-[r:BASIS]->()"
                             " RETURN count(r) AS n")[0]["n"] == 1


def test_sync_changed_on_empty_graph_rebuilds_and_deleted_works_go(conn, tmp_path, neo4j_driver):
    build(conn, tmp_path)
    with neo4j_driver.session() as s:
        s.run("MATCH (n) DETACH DELETE n")
    assert sync_changed(conn, neo4j_driver)["mode"] == "rebuild"
    with neo4j_driver.session() as s:  # PostgreSQL에 없는 규범문서는 증분 동기화에서 지운다
        s.run("CREATE (:Work {id: 'kr/reg/X/gone', fp: 'x'})")
    assert sync_changed(conn, neo4j_driver)["works"] == 1
    assert one(neo4j_driver, "MATCH (w:Work {id: 'kr/reg/X/gone'}) RETURN w") == []


def test_rebuild_real_file_is_idempotent(loaded, neo4j_driver):
    st = sync_graph(loaded, neo4j_driver)
    n = loaded.execute("SELECT count(DISTINCT vp.provision_version_id) AS n FROM regulation.version_provision vp"
                       " JOIN regulation.work_version v ON v.id = vp.work_version_id"
                       " WHERE v.effective_from IS NOT NULL").fetchone()["n"]
    assert st["works"] == 1 and st["provisions"] == n > 50 and st["relations"] > 5
    assert sync_graph(loaded, neo4j_driver) == st


def test_graph_lock_excludes_a_second_runner(migrated):
    import psycopg

    from reg.graph.sync import GRAPH_LOCK, graph_lock

    with psycopg.connect(migrated[0]) as a, psycopg.connect(migrated[0]) as b:
        with graph_lock(a):
            assert b.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (GRAPH_LOCK,)).fetchone()[0] is False
        assert b.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (GRAPH_LOCK,)).fetchone()[0] is True


def test_reference_to_a_path_no_version_has_becomes_missing_node(conn, tmp_path, neo4j_driver):
    build(conn, tmp_path)
    blob = LocalBlobStore(tmp_path)
    upsert_work(conn, "kr/reg/KASI/세칙", "INTERNAL_REG", "여비세칙", None, {})
    _ver(conn, blob, "kr/reg/KASI/세칙", "여비세칙", [Prov("a1", "article", "제1조", None, "「가상 연구법」 제9조에 따른다.")],
         date(2021, 1, 1), b"S1")
    rebuild_work(conn, "kr/reg/KASI/세칙", T)
    resolve_and_store(conn, "kr/reg/KASI/세칙")
    conn.commit()
    rebuild(conn, neo4j_driver)
    assert one(neo4j_driver, "MATCH (:Provision {work_id: 'kr/reg/KASI/세칙', path: 'a1'})-[r]->(m:MissingProvision)"
                             " RETURN m.key AS k, r.match AS m") == [{"k": "kr/law/L1|a9", "m": "missing"}]


def test_cli_and_task_sync_are_incremental(conn, tmp_path, neo4j_driver, monkeypatch):
    from typer.testing import CliRunner

    import reg.graph.cli as gcli
    from reg.graph import tasks as gt
    from reg.platform.settings import get_settings

    build(conn, tmp_path)
    url = neo4j_driver.get_server_info().address
    monkeypatch.setenv("REG_DATABASE_URL", _dsn(conn))
    monkeypatch.setenv("REG_NEO4J_URL", f"bolt://{url[0]}:{url[1]}")
    monkeypatch.setenv("REG_NEO4J_PASSWORD", "testpass1234")
    monkeypatch.setenv("REG_NEO4J_TARGET", "local")
    get_settings.cache_clear()
    try:
        out = CliRunner().invoke(gcli.graph, ["rebuild"])
        assert out.exit_code == 0 and "works" in out.output, out.output
        out = CliRunner().invoke(gcli.graph, ["sync", "--works", "kr/law/L1,kr/reg/KASI/여비"])
        assert out.exit_code == 0 and "'works': 2" in out.output, out.output
        assert gt.sync()["works"] == 0  # 바뀐 규범문서가 없으면 아무것도 하지 않는다
    finally:
        get_settings.cache_clear()
        conn.execute("DELETE FROM ops.pipeline_run")
        conn.commit()


def _dsn(conn) -> str:
    i = conn.info
    return f"postgresql://{i.user}:{i.password}@{i.host}:{i.port}/{i.dbname}"
