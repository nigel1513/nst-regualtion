from datetime import date

from reg.alerts.impact import analyze_version, severity
from reg.collect.archive import store
from reg.collect.sniff import FileKind
from reg.graph.sync import sync_graph
from reg.load.loader import add_version, rebuild_work, upsert_work
from reg.refs import resolve_and_store
from reg.storage.blob import LocalBlobStore
from reg.structure.effective import Effective
from reg.structure.model import ParsedDoc, Prov

T = date(2026, 10, 2)


def _ver(conn, blob, wid, title, provs, d, tag):
    sid = store(conn, blob, source="alio", url="u", content=b"%PDF" + tag, kind=FileKind("application/pdf", "pdf"),
                meta={}).id
    return add_version(conn, wid, sid, ParsedDoc(title, None, [], provs), Effective(d, "api", "CONFIRMED", d))


def law_v1():
    return [Prov("a5", "article", "제5조", "정산", "정산은 7일 이내에 한다."),
            Prov("a6", "article", "제6조", "기록", "기록한다.")]


def setup(conn, tmp_path, law_v2, v1=None):
    """가상 법률(제5조·제6조)과 그것을 인용하는 천문연 규정. 법률에 새 버전 law_v2를 더하고 그 버전 id를 돌려준다."""
    blob = LocalBlobStore(tmp_path)
    upsert_work(conn, "kr/law/L1", "법률", "가상 연구법", None, {})
    _ver(conn, blob, "kr/law/L1", "가상 연구법", v1 or law_v1(), date(2020, 1, 1), b"L1")
    rebuild_work(conn, "kr/law/L1", T)
    inst = conn.execute("INSERT INTO regulation.institution (code, name, kind) VALUES ('KASI','천문연','GRI')"
                        " ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name RETURNING id").fetchone()["id"]
    upsert_work(conn, "kr/reg/KASI/여비", "INTERNAL_REG", "여비규정", inst, {})
    _ver(conn, blob, "kr/reg/KASI/여비", "여비규정",
         [Prov("a3", "article", "제3조", "정산", "「가상 연구법」 제5조에 따라 정산한다."),
          Prov("a4", "article", "제4조", "기록", "「가상 연구법」 제6조를 참고한다."),
          Prov("a7", "article", "제7조", "기타", "제3조에도 불구하고 따로 정한다."),
          Prov("a8", "article", "제8조", "준용", "이 규정에 없는 사항은 「가상 연구법」을 따른다.")], date(2021, 1, 1), b"R1")
    rebuild_work(conn, "kr/reg/KASI/여비", T)
    for w in ("kr/law/L1", "kr/reg/KASI/여비"):
        resolve_and_store(conn, w)
    vid = _ver(conn, blob, "kr/law/L1", "가상 연구법", law_v2, date(2026, 1, 1), b"L2")
    rebuild_work(conn, "kr/law/L1", T)
    conn.commit()
    return vid


def test_severity_table():
    assert severity("DELETED", "CITATION") == "HIGH" and severity("MODIFIED", "BASIS") == "HIGH"
    assert severity("MODIFIED", "CITATION") == "MEDIUM" and severity("RENUMBERED", "BASIS") == "MEDIUM"
    assert severity("ADDED", "CITATION") == "LOW"


def test_modified_basis_creates_high_impact_once(conn, tmp_path, neo4j_driver):
    vid = setup(conn, tmp_path, [Prov("a5", "article", "제5조", "정산", "정산은 10일 이내에 한다."),
                                 Prov("a6", "article", "제6조", "기록", "기록한다.")])
    sync_graph(conn, neo4j_driver)
    rows = analyze_version(conn, neo4j_driver, "kr/law/L1", vid)
    got = [(r["affected_work_id"], r["affected_path"], r["cause_path"], r["severity"], r["rel_type"]) for r in rows]
    # a4(제6조 참조)는 변경 없음, a7은 같은 규정 안, a8은 법 전체를 참조하므로 낮음으로 한 번
    assert got == [("kr/reg/KASI/여비", "a3", "a5", "HIGH", "BASIS"), ("kr/reg/KASI/여비", "a8", "a5", "LOW", "CITATION")]
    assert analyze_version(conn, neo4j_driver, "kr/law/L1", vid) == []  # 재스캔해도 중복 없음
    assert conn.execute("SELECT count(*) AS n FROM regulation.change_impact").fetchone()["n"] == 2


def test_annotation_only_change_has_no_impact(conn, tmp_path, neo4j_driver):
    v2 = [Prov("a5", "article", "제5조", "정산", "정산은 7일 이내에 한다.", annotations=["<개정 2026.1.1.>"]),
          Prov("a6", "article", "제6조", "기록", "기록한다.")]
    vid = setup(conn, tmp_path, v2)
    sync_graph(conn, neo4j_driver)
    assert analyze_version(conn, neo4j_driver, "kr/law/L1", vid) == []


def test_deleted_target_is_high(conn, tmp_path, neo4j_driver):
    vid = setup(conn, tmp_path, [Prov("a5", "article", "제5조", "정산", "정산은 7일 이내에 한다.")])
    sync_graph(conn, neo4j_driver)
    rows = analyze_version(conn, neo4j_driver, "kr/law/L1", vid)
    assert [(r["affected_path"], r["cause_change"], r["severity"]) for r in rows] == \
        [("a4", "DELETED", "HIGH"), ("a8", "DELETED", "LOW")]


def test_backtest_replays_amendments_without_alerting(conn, tmp_path, neo4j_driver):
    from reg.alerts.backtest import backtest
    from reg.alerts.notify import build_notifications

    setup(conn, tmp_path, [Prov("a5", "article", "제5조", "정산", "정산은 10일 이내에 한다."),
                           Prov("a6", "article", "제6조", "기록", "기록한다.")])
    sync_graph(conn, neo4j_driver)
    st = backtest(conn, neo4j_driver)
    assert st["versions"] == 1 and st["impacts"] == 2 and st["by_severity"] == {"HIGH": 1, "LOW": 1}
    assert st["examples"][0]["affected_path"] == "a3"
    assert build_notifications(conn, {"KASI": ["a@x"]}) == 0  # 재생 결과로는 알림을 보내지 않는다


def test_added_articles_make_one_impact_per_work_level_reference(conn, tmp_path, neo4j_driver):
    v2 = law_v1() + [Prov("a7", "article", "제7조", "신설", "새로 정한다."),
                     Prov("a7.p1", "paragraph", "①", None, "세부.", "a7"),
                     Prov("a8", "article", "제8조", "신설", "또 정한다."),
                     Prov("supp@2026-01-01", "supplement", "부칙", None, "이 법은 2026년 1월 1일부터 시행한다.")]
    vid = setup(conn, tmp_path, v2)
    sync_graph(conn, neo4j_driver)
    rows = analyze_version(conn, neo4j_driver, "kr/law/L1", vid)
    assert [(r["affected_path"], r["cause_change"], r["cause_path"], r["severity"]) for r in rows] == \
        [("a8", "ADDED", "a7, a8", "LOW")]


def test_changes_under_one_referenced_article_make_one_impact(conn, tmp_path, neo4j_driver):
    def law(t1, t2):
        return [Prov("a5", "article", "제5조", "정산", ""), Prov("a5.p1", "paragraph", "①", None, t1, "a5"),
                Prov("a5.p2", "paragraph", "②", None, t2, "a5"), Prov("a6", "article", "제6조", "기록", "기록한다.")]
    vid = setup(conn, tmp_path, law("7일 이내 정산.", "증빙을 낸다."), v1=law("5일 이내 정산.", "증빙을 붙인다."))
    sync_graph(conn, neo4j_driver)
    rows = analyze_version(conn, neo4j_driver, "kr/law/L1", vid)
    assert [(r["affected_path"], r["cause_path"], r["cause_change"]) for r in rows] == \
        [("a3", "a5", "MODIFIED"), ("a8", "a5", "MODIFIED")]  # a8은 법 전체 참조


def test_missing_graph_raises_so_the_event_is_retried(conn, tmp_path, neo4j_driver):
    import pytest

    vid = setup(conn, tmp_path, [Prov("a5", "article", "제5조", "정산", "정산은 10일 이내에 한다."),
                                 Prov("a6", "article", "제6조", "기록", "기록한다.")])
    with neo4j_driver.session() as s:
        s.run("MATCH (n) WHERE any(l IN labels(n) WHERE l STARTS WITH 'Reg') DETACH DELETE n")
    with pytest.raises(LookupError):
        analyze_version(conn, neo4j_driver, "kr/law/L1", vid)


def test_second_hop_follows_delegation_at_paragraph_level_and_caps_severity(conn, tmp_path, neo4j_driver):
    vid = setup(conn, tmp_path, [Prov("a5", "article", "제5조", "정산", "정산은 10일 이내에 한다."),
                                 Prov("a6", "article", "제6조", "기록", "기록한다.")])
    sync_graph(conn, neo4j_driver)
    with neo4j_driver.session() as s:  # 세부지침 제2조가 여비규정 제3조(근거로 법 제5조를 인용)를 시행, 제4조(단순 인용)도 시행
        s.run("CREATE (a:RegProvision {key: 'kr/reg/KASI/지침|a2', work_id: 'kr/reg/KASI/지침', path: 'a2'}),"
              " (b:RegProvision {key: 'kr/reg/KASI/지침|a9', work_id: 'kr/reg/KASI/지침', path: 'a9'})"
              " WITH a, b MATCH (t:RegProvision {key: 'kr/reg/KASI/여비|a3'}), (u:RegProvision {key: 'kr/reg/KASI/여비|a8'})"
              " CREATE (a)-[:IMPLEMENTS {evidence: '여비규정 제3조', source_path: 'a2'}]->(t),"
              " (b)-[:IMPLEMENTS {evidence: '여비규정 제8조', source_path: 'a9'}]->(u)")
    rows = analyze_version(conn, neo4j_driver, "kr/law/L1", vid)
    hop2 = [(r["affected_work_id"], r["affected_path"], r["severity"]) for r in rows if r["hops"] == 2]
    assert hop2 == [("kr/reg/KASI/지침", "a2", "HIGH")]  # a8(법 전체 인용, 약한 관계)에서는 넘어가지 않는다


def test_backtest_inserts_resolved_and_skips_pending_versions(conn, tmp_path, neo4j_driver):
    import json

    from reg.alerts.backtest import backtest

    vid = setup(conn, tmp_path, [Prov("a5", "article", "제5조", "정산", "정산은 10일 이내에 한다."),
                                 Prov("a6", "article", "제6조", "기록", "기록한다.")])
    conn.execute("INSERT INTO regulation.outbox (topic, payload) VALUES ('regulation.version_loaded', %s)",
                 (json.dumps({"work_id": "kr/law/L1", "version_id": vid}),))
    conn.commit()
    sync_graph(conn, neo4j_driver)
    assert backtest(conn, neo4j_driver)["versions"] == 0  # 알림을 기다리는 실제 개정은 재생하지 않는다
    rows = analyze_version(conn, neo4j_driver, "kr/law/L1", vid, status="RESOLVED", note="backtest")
    assert rows and {r["status"] for r in rows} == {"RESOLVED"}
