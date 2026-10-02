from datetime import date
from pathlib import Path

from reg.core.extract import extract
from reg.core.quality import Issue, check, record
from reg.core.effective import Effective
from reg.core.model import ParsedDoc, Prov
from reg.core.parse import parse_blocks

S = Path(__file__).parent / "fixtures" / "samples"
OK = Effective(date(2024, 1, 1), "supplement", "CONFIRMED", None)


def arts(*nums, deleted=()):
    return ParsedDoc("x", None, [], [Prov(f"a{n}", "article", f"제{n}조", "t", "삭제" if n in deleted else "본문입니다 충분히 길게 씁니다",
                                          deleted=n in deleted) for n in nums])


def test_gap_detected_and_deleted_counts_as_present():
    assert [i.kind for i in check(arts(1, 2, 4), OK)] == ["PARSE"]
    assert check(arts(1, 2, 3, deleted=(2,)), OK) == []


def test_effective_status_issues():
    assert [i.kind for i in check(arts(1), Effective(None, "none", "UNCERTAIN", None))] == ["EFFECTIVE_DATE"]
    assert [i.kind for i in check(arts(1), Effective(date(2024, 1, 1), "supplement", "CONFLICT", None))] == ["CONFLICT"]


def test_kasi_toc_matches_body_and_nst_has_no_toc():
    kasi = parse_blocks(extract((S / "kasi-yeobi-339.pdf").read_bytes(), "application/pdf", "a.pdf"))
    assert len(kasi.meta["toc"]) >= 20 and check(kasi, OK) == []
    nst = parse_blocks(extract((S / "nst-yeobi-18.hwp").read_bytes(), "application/x-hwp", "a.hwp"))
    assert "toc" not in nst.meta and all(i.detail.get("check") != "toc" for i in check(nst, OK))


def test_record_is_idempotent_and_sets_status(conn, tmp_path):
    from tests.test_refs import _load

    _load(conn, tmp_path, "kr/reg/X/a", "INTERNAL_REG", "a", [Prov("a1", "article", "제1조", "t", "본문입니다")])
    vid = conn.execute("SELECT id FROM regulation.work_version").fetchone()["id"]
    issues = [Issue("PARSE", {"check": "gap", "missing": [3]}), Issue("EFFECTIVE_DATE", {})]
    assert record(conn, "kr/reg/X/a", vid, issues) == "REVIEW"
    record(conn, "kr/reg/X/a", vid, issues)
    assert conn.execute("SELECT count(*) AS n FROM regulation.review_task").fetchone()["n"] == 2
    assert record(conn, "kr/reg/X/a", vid, [Issue("EFFECTIVE_DATE", {})]) == "PASSED"
