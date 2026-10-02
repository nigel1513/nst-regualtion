# tests/core/test_refs_resolve.py
from datetime import date

from reg.core.effective import Effective
from reg.core.ingest.loader import add_version, rebuild_work, upsert_work
from reg.core.model import ParsedDoc, Prov
from reg.core.refs import resolve_and_store
from reg.platform.archive import store
from reg.platform.sniff import FileKind
from reg.platform.storage.blob import LocalBlobStore


def _inst(conn) -> int:
    return conn.execute("INSERT INTO regulation.institution (code, name, kind, aliases)"
                        " VALUES ('ETRI','한국전자통신연구원','GRI', ARRAY['에트리','전자통신연구원'])"
                        " ON CONFLICT (code) DO UPDATE SET aliases = EXCLUDED.aliases RETURNING id").fetchone()["id"]


def _load(conn, tmp_path, wid, title, provs, inst):
    upsert_work(conn, wid, "INTERNAL_REG", title, inst, {})
    sid = store(conn, LocalBlobStore(tmp_path), source="alio", url="u", content=b"%PDF" + wid.encode(),
                kind=FileKind("application/pdf", "pdf"), meta={}).id
    add_version(conn, wid, sid, ParsedDoc(title, None, [], provs),
                Effective(date(2024, 1, 1), "supplement", "CONFIRMED", None))
    rebuild_work(conn, wid, date(2026, 10, 2))


def _refs(conn, wid):
    return conn.execute("SELECT evidence_text, rel_type, target_kind, target_work_id, target_path, target_name,"
                        " resolution, extractor, confidence FROM regulation.reference WHERE work_id = %s"
                        " ORDER BY span_start", (wid,)).fetchall()


def test_unbracketed_regulation_name_never_links_to_self(conn, tmp_path):
    inst = _inst(conn)
    _load(conn, tmp_path, "kr/reg/ETRI/연구관리규정", "연구관리규정",
          [Prov("a2", "article", "제2조", "정의", "이 규정에서 사용하는 용어는 다음과 같다.")], inst)
    _load(conn, tmp_path, "kr/reg/ETRI/오픈소스연구활동요령", "오픈소스연구활동요령", [
        Prov("a1", "article", "제1조", "목적", "이 요령은 연구관리규정 제2조(정의)에 의거, 오픈소스 연구 활동에 관하여"
             " 필요한 사항을 정함으로써 목적으로 한다."),
        Prov("a2", "article", "제2조", "정의", "정의한다."),
        Prov("a3", "article", "제3조", "기타", "없는요령 제5조에 따른다.")], inst)
    resolve_and_store(conn, "kr/reg/ETRI/오픈소스연구활동요령")
    r = {x["evidence_text"]: x for x in _refs(conn, "kr/reg/ETRI/오픈소스연구활동요령")}
    a = r["연구관리규정 제2조"]
    assert (a["target_work_id"], a["target_path"], a["rel_type"], a["resolution"], a["extractor"]) == \
           ("kr/reg/ETRI/연구관리규정", "a2", "IMPLEMENTS", "RESOLVED", "rule:name")
    b = r["없는요령 제5조"]  # 같은 기관에 없는 이름: 자기 제5조가 아니라 미해석 외부 참조
    assert (b["target_kind"], b["target_work_id"], b["target_name"], b["resolution"]) == \
           ("EXTERNAL_UNRESOLVED", None, "없는요령", "UNRESOLVED")


def test_overlapping_titles_resolve_exactly(conn, tmp_path):
    """Review Focus 2: 직제규정/직제규정시행요령, 인사규정/인사관리요령, 법령 이름과 기관 규정 이름."""
    inst = _inst(conn)
    for wid, t in [("kr/reg/ETRI/직제규정", "직제규정"), ("kr/reg/ETRI/직제규정시행요령", "직제규정시행요령"),
                   ("kr/reg/ETRI/인사관리요령", "인사관리요령"), ("kr/reg/ETRI/여비규정", "여비규정")]:
        _load(conn, tmp_path, wid, t, [Prov("a3", "article", "제3조", "가", "가")], inst)
    _load(conn, tmp_path, "kr/reg/ETRI/인사규정", "인사규정", [
        Prov("a1", "article", "제1조", "기타", "직제규정 제3조, 직제규정시행요령 제3조, 공무원 여비규정 제3조를 따른다."),
        Prov("supp#1", "supplement", "부칙", None, "②(타 요령의 개정) 에트리 인사관리요령 일부를 다음과 같이 개정한다."
             " 제3조 중 “가”를 “나”로 한다.")], inst)
    resolve_and_store(conn, "kr/reg/ETRI/인사규정")
    got = {x["evidence_text"]: (x["target_work_id"], x["target_name"]) for x in _refs(conn, "kr/reg/ETRI/인사규정")}
    assert got["직제규정 제3조"] == ("kr/reg/ETRI/직제규정", "직제규정")
    assert got["직제규정시행요령 제3조"] == ("kr/reg/ETRI/직제규정시행요령", "직제규정시행요령")
    assert got["여비규정 제3조"] == ("kr/reg/ETRI/여비규정", "여비규정")      # 한 덩어리 이름은 그대로 맞는다
    assert got["제3조"] == ("kr/reg/ETRI/인사관리요령", "에트리 인사관리요령")  # 개정 부칙 범위 + 기관 약칭(aliases) 접두어
    seeds = {r["name"] for r in conn.execute("SELECT name FROM regulation.law_seed").fetchall()}
    assert "법" not in seeds and "시행령" not in seeds


def test_delegation_to_named_regulation_is_work_target(conn, tmp_path):
    inst = _inst(conn)
    _load(conn, tmp_path, "kr/reg/ETRI/인사관리요령", "인사관리요령", [Prov("a1", "article", "제1조", "목적", "가")], inst)
    _load(conn, tmp_path, "kr/reg/ETRI/인사규정", "인사규정", [
        Prov("a7", "article", "제7조", "수습", ""),
        Prov("a7.p1", "paragraph", "①", None, "수습에 관한 세부사항은 인사관리요령에서 정한다.", "a7"),
        Prov("a8", "article", "제8조", "기타", "세부사항은 원장이 따로 정한다."),
        Prov("a9", "article", "제9조", "여비", "여비는 여비규정에 의하여 지급하고 심사기준에 따라 정한다.")], inst)
    resolve_and_store(conn, "kr/reg/ETRI/인사규정")
    rows = _refs(conn, "kr/reg/ETRI/인사규정")
    d = {(x["target_kind"], x["target_work_id"], x["resolution"]) for x in rows if x["rel_type"] == "DELEGATION"}
    assert d == {("WORK", "kr/reg/ETRI/인사관리요령", "RESOLVED"), ("NONE", None, "RESOLVED")}
    assert not [x for x in rows if x["target_name"] in ("여비규정", "심사기준")]  # 해석 못 한 이름만 참조는 남기지 않는다
