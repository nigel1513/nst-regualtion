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


def setup(conn, tmp_path, law_v2):
    """가상 법률(제5조·제6조)과 그것을 인용하는 천문연 규정. 법률에 새 버전 law_v2를 더하고 그 버전 id를 돌려준다."""
    blob = LocalBlobStore(tmp_path)
    upsert_work(conn, "kr/law/L1", "법률", "가상 연구법", None, {})
    _ver(conn, blob, "kr/law/L1", "가상 연구법", law_v1(), date(2020, 1, 1), b"L1")
    rebuild_work(conn, "kr/law/L1", T)
    inst = conn.execute("INSERT INTO regulation.institution (code, name, kind) VALUES ('KASI','천문연','GRI')"
                        " ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name RETURNING id").fetchone()["id"]
    upsert_work(conn, "kr/reg/KASI/여비", "INTERNAL_REG", "여비규정", inst, {})
    _ver(conn, blob, "kr/reg/KASI/여비", "여비규정",
         [Prov("a3", "article", "제3조", "정산", "「가상 연구법」 제5조에 따라 정산한다."),
          Prov("a4", "article", "제4조", "기록", "「가상 연구법」 제6조를 참고한다."),
          Prov("a7", "article", "제7조", "기타", "제3조에도 불구하고 따로 정한다.")], date(2021, 1, 1), b"R1")
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
    assert got == [("kr/reg/KASI/여비", "a3", "a5", "HIGH", "BASIS")]  # a4(제6조 참조)는 변경 없음, a7은 같은 규정 안
    assert analyze_version(conn, neo4j_driver, "kr/law/L1", vid) == []  # 재스캔해도 중복 없음
    assert conn.execute("SELECT count(*) AS n FROM regulation.change_impact").fetchone()["n"] == 1


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
    assert [(r["affected_path"], r["cause_change"], r["severity"]) for r in rows] == [("a4", "DELETED", "HIGH")]
