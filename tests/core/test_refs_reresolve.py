# tests/core/test_refs_reresolve.py
"""일괄 적재 뒤 재해석 (reg refs reresolve, reg_process.refs_reresolve). 바뀐 work만 다시 쓴다."""
from datetime import date

from typer.testing import CliRunner

from reg.core.effective import Effective
from reg.core.ingest.loader import add_version, rebuild_work, upsert_work
from reg.core.model import ParsedDoc, Prov
from reg.core.quality import record_reference_tasks
from reg.core.refs import reresolve, resolve_and_store
from reg.platform.archive import store
from reg.platform.sniff import FileKind
from reg.platform.storage.blob import LocalBlobStore


def _inst(conn) -> int:
    return conn.execute("INSERT INTO regulation.institution (code, name, kind) VALUES ('KIGAM','한국지질자원연구원','GRI')"
                        " ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name RETURNING id").fetchone()["id"]


def _load(conn, tmp_path, wid, title, provs):
    upsert_work(conn, wid, "INTERNAL_REG", title, _inst(conn), {})
    sid = store(conn, LocalBlobStore(tmp_path), source="alio", url="u", content=b"%PDF" + wid.encode(),
                kind=FileKind("application/pdf", "pdf"), meta={}).id
    add_version(conn, wid, sid, ParsedDoc(title, None, [], provs), Effective(date(2024, 1, 1), "supplement", "CONFIRMED", None))
    rebuild_work(conn, wid, date(2026, 10, 3))


EARLY = "kr/reg/KIGAM/석좌연구원임용지침"
LATE = "kr/reg/KIGAM/인사규정"
OTHER = "kr/reg/KIGAM/여비규정"


def _setup(conn, tmp_path):
    """석좌연구원임용지침이 먼저 처리되어 아직 없던 인사규정을 가리킨다 (처리 순서 문제, 02-data-loading §5.3)."""
    _load(conn, tmp_path, EARLY, "석좌연구원임용지침", [
        Prov("a10", "article", "제10조", "해임", "석좌연구원으로 임용된 자가 인사규정 제12조(결격사유) 또는 제19조(실격)에"
             " 해당하는 경우에는 해임한다."),
        Prov("a11", "article", "제11조", "준용", "제10조에 따른다.")])
    _load(conn, tmp_path, OTHER, "여비규정", [
        Prov("a1", "article", "제1조", "목적", "제2조에 따른다."), Prov("a2", "article", "제2조", "정의", "정의"),
        Prov("a3", "article", "제3조", "기타", "없는규정 제5조에 따른다.")])
    for w in (EARLY, OTHER):
        resolve_and_store(conn, w)
        record_reference_tasks(conn, w)
    _load(conn, tmp_path, LATE, "인사규정", [Prov("a12", "article", "제12조", "결격사유", "결격"),
                                         Prov("a19", "article", "제19조", "실격", "실격")])
    resolve_and_store(conn, LATE)
    conn.commit()


def _refs(conn, wid):
    return conn.execute("SELECT id, evidence_text, target_work_id, target_path, resolution FROM regulation.reference"
                        " WHERE work_id = %s ORDER BY span_start", (wid,)).fetchall()


def test_reresolve_rewrites_only_changed_works(conn, tmp_path):
    _setup(conn, tmp_path)
    assert {r["resolution"] for r in _refs(conn, EARLY) if r["target_work_id"] != EARLY} == {"UNRESOLVED"}
    other_ids = [r["id"] for r in _refs(conn, OTHER)]
    assert conn.execute("SELECT count(*) AS n FROM regulation.review_task WHERE kind = 'REFERENCE' AND work_id = %s"
                        " AND status = 'OPEN'", (EARLY,)).fetchone()["n"] == 2

    st = reresolve(conn)
    assert (st["works"], st["changed"], st["unchanged"], st["failed"]) == (2, 1, 1, 0)  # 미해석이 있는 work만 본다
    assert st["resolved_before"] + 2 == st["resolved_after"]
    got = {(r["evidence_text"], r["target_work_id"], r["target_path"], r["resolution"]) for r in _refs(conn, EARLY)}
    assert ("인사규정 제12조", LATE, "a12", "RESOLVED") in got and ("제19조", LATE, "a19", "RESOLVED") in got
    assert [r["id"] for r in _refs(conn, OTHER)] == other_ids  # 바뀌지 않은 work는 다시 쓰지 않는다 (그래프 지문 유지)
    assert conn.execute("SELECT count(*) AS n FROM regulation.review_task WHERE kind = 'REFERENCE' AND work_id = %s"
                        " AND status = 'OPEN'", (EARLY,)).fetchone()["n"] == 0  # 검수 작업도 닫힌다

    again = reresolve(conn)
    assert (again["changed"], again["unchanged"]) == (0, 1)  # 남은 것은 여비규정의 '없는규정'뿐


def test_reresolve_dry_run_and_work_filter(conn, tmp_path):
    _setup(conn, tmp_path)
    before = _refs(conn, EARLY)
    st = reresolve(conn, [EARLY], dry_run=True)
    assert (st["works"], st["changed"], st["resolved_after"] - st["resolved_before"]) == (1, 1, 2)
    assert _refs(conn, EARLY) == before
    assert reresolve(conn, [OTHER])["changed"] == 0


def test_cli_refs_reresolve_dry_run(conn, tmp_path, monkeypatch, migrated):
    from reg.cli import app
    from reg.platform.settings import get_settings

    _setup(conn, tmp_path)
    monkeypatch.setenv("REG_DATABASE_URL", migrated[0])
    get_settings.cache_clear()
    try:
        out = CliRunner().invoke(app, ["refs", "reresolve", "--works", EARLY, "--dry-run"])
    finally:
        get_settings.cache_clear()
    assert out.exit_code == 0, out.output
    assert "changed=1" in out.output and "dry-run" in out.output
    assert {r["resolution"] for r in _refs(conn, EARLY) if r["target_work_id"] != EARLY} == {"UNRESOLVED"}


def test_task_skips_when_nothing_was_loaded_and_runs_otherwise(conn, tmp_path, monkeypatch, migrated):
    from reg.core.ingest.tasks import reresolve_refs
    from reg.platform.settings import get_settings

    _setup(conn, tmp_path)
    monkeypatch.setenv("REG_DATABASE_URL", migrated[0])
    get_settings.cache_clear()
    try:
        assert reresolve_refs({"claimed": 0, "ok": 0, "failed": 0, "parked": 0})["skipped"]
        st = reresolve_refs({"claimed": 3, "ok": 3, "failed": 0, "parked": 0})
    finally:
        get_settings.cache_clear()
    assert (st["changed"], st["failed"]) == (1, 0)
    runs = [r["status"] for r in conn.execute("SELECT status FROM ops.pipeline_run WHERE task_id = 'core.refs_reresolve'")]
    assert runs == ["success", "success"]
