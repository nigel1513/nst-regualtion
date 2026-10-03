from datetime import date

import pytest

from reg.graph.query import expand, lineage, neighborhood
from reg.graph.sync import rebuild
from tests.test_graph import build, pv

W = "kr/reg/KASI/출장"


@pytest.fixture
def graph(conn, tmp_path, neo4j_driver):
    vid = build(conn, tmp_path)
    rebuild(conn, neo4j_driver)
    return conn, vid


@pytest.mark.parametrize("term,seed,definition", [
    ("출장", "a3.p2", "a2.i1"), ("여비", "a3.p1", "a2.i2"), ("일비", "a3.p2", "a2.i3"),
    ("숙박비", "a4", "a2.i4"), ("출장자", "a3.p1", "a2.i5")])
def test_term_question_evidence_includes_definition(graph, neo4j_driver, term, seed, definition):
    """spec §3: 정의 조항이 있는 규정에서 용어 질문의 근거에 정의 조항이 포함된다 (5사례)."""
    conn, _ = graph
    got = expand(neo4j_driver, [pv(conn, W, seed)])
    hit = [g for g in got if g["path"] == definition]
    assert hit and hit[0]["reason"] == f"용어 정의: {term}" and hit[0]["work_id"] == W
    assert hit[0]["full_label"] == f"출장규정 제2조 제{definition[-1]}호"


def test_exception_and_parent_article(graph, neo4j_driver):
    conn, _ = graph
    got = {g["path"]: g for g in expand(neo4j_driver, [pv(conn, W, "a3.p1")])}
    assert got["a3"]["reason"] == "상위 조문"
    assert got["a5"]["reason"] == "예외 조항" and got["a5"]["direction"] == "in"  # 제3조에도 불구하고 → 제3조 제1항 근거에도
    assert pv(conn, W, "a3.p1") not in {g["pv_id"] for g in got.values()}  # 시작 조항은 빼고 돌려준다


def test_outgoing_reference_follows_as_of_and_depth(graph, neo4j_driver):
    conn, _ = graph
    a3 = pv(conn, "kr/reg/KASI/여비", "a3")
    now = [g for g in expand(neo4j_driver, [a3]) if g["work_id"] == "kr/law/L1"]
    assert [(g["path"], g["pv_id"], g["reason"], g["hops"]) for g in now] == \
        [("a5", pv(conn, "kr/law/L1", "a5"), "근거 조항", 1)]  # 현행 판본으로 옮겨 준다
    old = [g for g in expand(neo4j_driver, [a3], as_of=date(2021, 6, 1)) if g["work_id"] == "kr/law/L1"]
    assert [g["pv_id"] for g in old] == [pv(conn, "kr/law/L1", "a5", date(2020, 1, 1))]
    a7 = pv(conn, "kr/reg/KASI/여비", "a7")
    one = {g["path"]: g for g in expand(neo4j_driver, [a7], depth=1)}
    assert one["a3"]["reason"] == "예외의 원칙 조항" and "a5" not in one
    two = {(g["work_id"], g["path"]): g for g in expand(neo4j_driver, [a7], depth=2)}
    assert two[("kr/law/L1", "a5")]["hops"] == 2 and two[("kr/law/L1", "a5")]["via"] == a3


def test_neighborhood_nodes_and_edges(graph, neo4j_driver):
    conn, _ = graph
    a3 = pv(conn, "kr/reg/KASI/여비", "a3")
    n1 = neighborhood(neo4j_driver, a3, depth=1)
    ids = {n["id"] for n in n1["nodes"]}
    law_v1 = f"pv:{pv(conn, 'kr/law/L1', 'a5', date(2020, 1, 1))}"
    assert n1["center"] == f"pv:{a3}" and {f"pv:{a3}", law_v1, f"pv:{pv(conn, 'kr/reg/KASI/여비', 'a7')}"} <= ids
    assert {(e["source"], e["type"], e["target"]) for e in n1["edges"]} >= {(f"pv:{a3}", "BASIS", law_v1)}
    assert any(e["type"] == "CONTAINS" and e["target"] == f"pv:{a3}" and e["source"].startswith("ver:") for e in n1["edges"])
    assert f"pv:{pv(conn, 'kr/law/L1', 'a5')}" not in ids
    n2 = neighborhood(neo4j_driver, a3, depth=2)
    assert f"pv:{pv(conn, 'kr/law/L1', 'a5')}" in {n["id"] for n in n2["nodes"]}  # 대상 조항의 개정 계보까지
    t = neighborhood(neo4j_driver, pv(conn, W, "a3.p1"), depth=1)
    assert {"term:kr/reg/KASI/출장|여비", f"pv:{pv(conn, W, 'a2.i2')}"} <= {n["id"] for n in t["nodes"]}
    assert neighborhood(neo4j_driver, 999999999) is None


def test_lineage_chain(graph, neo4j_driver):
    conn, vid = graph
    v1, v2 = pv(conn, "kr/law/L1", "a5", date(2020, 1, 1)), pv(conn, "kr/law/L1", "a5")
    got = lineage(neo4j_driver, v2)
    assert [(e["pv_id"], e["valid_from"], e["valid_to"], e["change"]) for e in got["entries"]] == \
        [(v1, "2020-01-01", "2026-01-01", None), (v2, "2026-01-01", None, "MODIFIED")]
    assert got["entries"][1]["from_pv"] == v1 and got["deleted_in"] is None
    gone = lineage(neo4j_driver, pv(conn, "kr/law/L1", "a6", date(2020, 1, 1)))
    assert gone["deleted_in"] == {"version": vid, "effective_from": "2026-01-01"}
    assert lineage(neo4j_driver, 999999999) is None
