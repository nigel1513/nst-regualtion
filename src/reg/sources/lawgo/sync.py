"""일 변경분·주간 전체 대조 (spec §3A.4). 네트워크는 client, 해석은 xml, DB 쓰기는 mirror가 맡는다.

- 일: 법령·행정규칙 목록을 최신순(sort=ddes)으로 받아 없는 MST만 본문을 받는다. 마지막 성공일보다
  buffer_days 이전 공포일이 나오면 멈춘다. 변경이력 API는 쓰지 않는다.
- 주: 전체 목록 대조(누락 보충·폐지), 행정규칙 카탈로그, 선별 행정규칙, 법령 별표 전체 목록.
- 항목 하나의 실패는 errors에 남기고 다음으로 간다. 키·차단 신호는 즉시 멈춘다.
"""
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from reg.core.ingest.loader import norm_title as norm_name
from reg.platform import outbox
from reg.platform.archive import store
from reg.platform.http import StopCollecting
from reg.platform.sniff import FileKind
from reg.platform.storage.blob import BlobStore
from reg.sources.lawgo import urls
from reg.sources.lawgo.client import LawGoClient
from reg.sources.lawgo.config import LawgoConfig
from reg.sources.lawgo.errors import KeyNotApproved, KeyRejected, LawGoError, ResponseChanged
from reg.sources.lawgo.mirror import (
    VersionHeader,
    apply_version,
    catalog_row,
    has_version,
    mark_abolished,
    record_annexes,
    store_annex_body,
    upsert_catalog,
)
from reg.sources.lawgo.select import selected_admruls
from reg.sources.lawgo.xml import AdmrulRow, LawRow, parse_admrul_xml, parse_law_xml, parse_list, row_date

XML = FileKind("application/xml", "xml")
FATAL = (KeyNotApproved, KeyRejected, StopCollecting)
MAX_ANNEX_PAGES = 20


@dataclass
class Ctx:
    conn: Any
    client: LawGoClient
    blob: BlobStore
    cfg: LawgoConfig
    run_id: int | None = None


def new_stats() -> dict:
    return {"law_new": 0, "admrul_new": 0, "abolished": 0, "catalog": 0, "annex_new": 0, "annex_bodies": 0,
            "errors": []}


def guarded(ctx: Ctx, st: dict, label: str, fn: Callable[[], Any]) -> Any:
    """항목 하나 = 트랜잭션 하나. 키·차단 오류는 다시 던지고, 그 밖의 오류는 기록 후 None."""
    try:
        out = fn()
    except FATAL:
        ctx.conn.rollback()
        raise
    except Exception as e:
        ctx.conn.rollback()
        st["errors"].append(f"{label}: {type(e).__name__}: {e}"[:300])
        return None
    ctx.conn.commit()
    return out


def canary(client) -> dict:
    """최소 요청 3개로 응답 구조를 확인한다. 다르면 원인이 보이는 예외로 멈춘다 (spec §1A.6)."""
    lp = parse_list("law", client.search("law", display=1, sort="ddes"))
    if lp.total < 1000 or not lp.rows:
        raise ResponseChanged(f"law 목록 응답이 비정상입니다: totalCnt={lp.total}, 행 {len(lp.rows)}개")
    probe = lp.rows[0]
    doc = parse_law_xml(client.service("law", probe.mst))
    arts = sum(1 for p in doc.provisions if p.unit == "article")
    if not arts:
        raise ResponseChanged(f"law 본문 {probe.mst}: <조문단위>에서 조문을 하나도 찾지 못했습니다")
    adm = parse_list("admrul", client.search("admrul", display=1, sort="ddes"))
    if adm.total < 1000:
        raise ResponseChanged(f"admrul 목록 응답이 비정상입니다: totalCnt={adm.total}")
    return {"law_total": lp.total, "admrul_total": adm.total, "probe_mst": probe.mst, "probe_articles": arts}


def ingest_law(ctx: Ctx, row: LawRow) -> dict:
    data = ctx.client.service("law", row.mst)
    doc = parse_law_xml(data)
    sd = store(ctx.conn, ctx.blob, source="lawgo", url=urls.drf_xml("law", row.mst), content=data, kind=XML,
               meta={"law_id": row.law_id, "mst": row.mst, "name": row.name})
    return apply_version(ctx.conn, VersionHeader.from_law(row), doc, sd.id, ctx.run_id)


def ingest_admrul(ctx: Ctx, row: AdmrulRow) -> dict:
    data = ctx.client.service("admrul", row.seq)
    doc = parse_admrul_xml(data)
    sd = store(ctx.conn, ctx.blob, source="lawgo", url=urls.drf_xml("admrul", row.seq), content=data, kind=XML,
               meta={"law_id": row.master_id, "mst": row.seq, "name": row.name})
    return apply_version(ctx.conn, VersionHeader.from_admrul(row), doc, sd.id, ctx.run_id)


def refresh_annexes(ctx: Ctx, family: str, law_id: str, name: str) -> int:
    """search=2(관련 법령명, 포함 검색) 결과를 관련법령ID로 거른다 (판정 R4)."""
    target = "licbyl" if family == "law" else "admbyl"
    rows, page, complete = [], 1, False
    while page <= MAX_ANNEX_PAGES:
        lp = parse_list(target, ctx.client.search(target, search=2, query=name, display=100, page=page))
        rows += [r for r in lp.rows if r.master_id == law_id]
        if not lp.rows or page * 100 >= lp.total:
            complete = True
            break
        page += 1
    return record_annexes(ctx.conn, law_id, family, rows, complete=complete)


def scan_recent(ctx: Ctx, target: str, since: date) -> list:
    """최신순 목록을 앞에서부터. 연혁 행도 돌려준다(호출자가 거른다)."""
    stop = since - timedelta(days=ctx.cfg.buffer_days)
    out, page = [], 1
    while True:
        lp = parse_list(target, ctx.client.search(target, page=page, display=ctx.cfg.page_size, sort="ddes"))
        out += lp.rows
        dates = [d for r in lp.rows if (d := row_date(r))]
        if not lp.rows or page * ctx.cfg.page_size >= lp.total or (dates and min(dates) < stop):
            return out
        page += 1


def list_all(ctx: Ctx, target: str) -> list:
    out, page, total = [], 1, 0
    while True:
        lp = parse_list(target, ctx.client.search(target, page=page, display=ctx.cfg.page_size))
        out += lp.rows
        total = lp.total
        if not lp.rows or len(out) >= lp.total:
            break
        page += 1
    if len(out) < total * ctx.cfg.abolish_min_ratio:
        raise ResponseChanged(f"{target} 전체 목록이 {len(out)}/{total}건에서 끊겼습니다")
    return out


def ensure_admruls(ctx: Ctx, selected: dict[str, str], st: dict) -> None:
    for admrul_id, name in sorted(selected.items()):
        row = catalog_row(ctx.conn, admrul_id)
        if row is None or not row.seq or has_version(ctx.conn, row.seq):
            continue
        if guarded(ctx, st, f"admrul {row.seq} {name}", lambda row=row: ingest_admrul(ctx, row)) is not None:
            st["admrul_new"] += 1
            st["annex_new"] += guarded(ctx, st, f"admbyl {name}",
                                       lambda row=row: refresh_annexes(ctx, "admrul", row.master_id, row.name)) or 0


def sync_catalog(ctx: Ctx) -> int:
    rows = list_all(ctx, "admrul")
    seen = sorted({r.admrul_id for r in rows})
    known = ctx.conn.execute("SELECT count(*) AS n FROM law.admrul_catalog WHERE status = '현행'").fetchone()["n"]
    if known and len(seen) < known * ctx.cfg.abolish_min_ratio:
        raise ResponseChanged(f"admrul 전체 목록이 {len(seen)}건으로 기존 현행 {known}건보다 너무 적습니다."
                              " 폐지 처리를 멈춥니다")
    n = upsert_catalog(ctx.conn, rows)
    ctx.conn.execute("UPDATE law.admrul_catalog SET status = '폐지' WHERE status = '현행' AND NOT (admrul_id = ANY(%s))",
                     (seen,))
    ctx.conn.commit()
    return n


def refresh_all_law_annexes(ctx: Ctx, st: dict) -> int:
    """licbyl 전체 목록(약 398쪽)으로 미러 법령의 별표를 한 번에 맞춘다."""
    masters = {r["law_id"] for r in ctx.conn.execute(
        "SELECT law_id FROM law.law_master WHERE family = 'law'").fetchall()}
    by_owner: dict[str, list] = {}
    for a in list_all(ctx, "licbyl"):
        if a.master_id in masters:
            by_owner.setdefault(a.master_id, []).append(a)
    n = 0
    for law_id in sorted(masters):
        n += guarded(ctx, st, f"licbyl {law_id}",
                     lambda law_id=law_id: record_annexes(ctx.conn, law_id, "law", by_owner.get(law_id, []))) or 0
    return n


def fetch_annex_bodies(ctx: Ctx, st: dict, limit: int) -> int:
    """밀린 별표 본문을 오래된 것부터 limit건 (판정 R6). HTML은 원본 그대로, PDF는 R5."""
    rows = ctx.conn.execute("SELECT seq, family, pdf_path FROM law.annex WHERE is_current AND html_key IS NULL"
                            " ORDER BY first_seen_at, seq LIMIT %s", (limit,)).fetchall()
    n = 0
    for r in rows:
        def one(r=r) -> int:
            html = ctx.client.annex_html("licbyl" if r["family"] == "law" else "admbyl", r["seq"])
            pdf = None
            if ctx.cfg.annex_store_pdf and r["pdf_path"]:
                data = ctx.client.file(r["pdf_path"])
                pdf = data if data.startswith(b"%PDF") else None
            store_annex_body(ctx.conn, ctx.blob, r["seq"], html, pdf)
            return 1
        n += guarded(ctx, st, f"annex {r['seq']}", one) or 0
    return n


def sync_daily(ctx: Ctx, since: date) -> dict:
    st = new_stats() | {"since": since.isoformat()}
    for r in scan_recent(ctx, "law", since):
        if r.status != "현행" or has_version(ctx.conn, r.mst):
            continue
        if guarded(ctx, st, f"law {r.mst} {r.name}", lambda r=r: ingest_law(ctx, r)) is not None:
            st["law_new"] += 1
            st["annex_new"] += guarded(ctx, st, f"licbyl {r.name}",
                                       lambda r=r: refresh_annexes(ctx, "law", r.law_id, r.name)) or 0
    recent = scan_recent(ctx, "admrul", since)
    st["catalog"] = guarded(ctx, st, "admrul catalog", lambda: upsert_catalog(ctx.conn, recent)) or 0
    ensure_admruls(ctx, selected_admruls(ctx.conn, ctx.cfg), st)
    st["annex_bodies"] = fetch_annex_bodies(ctx, st, ctx.cfg.annex_body_limit)
    return st


def sync_full(ctx: Ctx) -> dict:
    st = new_stats()
    rows = [r for r in list_all(ctx, "law") if r.status == "현행"]
    seen = {r.law_id for r in rows}
    known = {r["law_id"] for r in ctx.conn.execute(
        "SELECT law_id FROM law.law_master WHERE family = 'law' AND status = '현행'").fetchall()}
    if known and len(seen) < len(known) * ctx.cfg.abolish_min_ratio:
        raise ResponseChanged(f"law 전체 목록이 {len(seen)}건으로 기존 현행 {len(known)}건보다 너무 적습니다."
                              " 폐지 처리를 멈춥니다")
    for r in rows:
        if not has_version(ctx.conn, r.mst) and guarded(
                ctx, st, f"law {r.mst} {r.name}", lambda r=r: ingest_law(ctx, r)) is not None:
            st["law_new"] += 1
    for law_id in sorted(known - seen):
        st["abolished"] += int(bool(guarded(ctx, st, f"abolish {law_id}",
                                            lambda law_id=law_id: mark_abolished(ctx.conn, law_id, ctx.run_id))))
    st["catalog"] = sync_catalog(ctx)
    ensure_admruls(ctx, selected_admruls(ctx.conn, ctx.cfg), st)
    gone = ctx.conn.execute(
        "SELECT m.law_id FROM law.law_master m JOIN law.admrul_catalog c ON m.law_id = 'admrul:' || c.admrul_id"
        " WHERE m.status = '현행' AND c.status = '폐지'").fetchall()
    for g in gone:
        st["abolished"] += int(bool(guarded(ctx, st, f"abolish {g['law_id']}",
                                            lambda g=g: mark_abolished(ctx.conn, g["law_id"], ctx.run_id))))
    for m in ctx.conn.execute("SELECT law_id, name FROM law.law_master WHERE family = 'admrul' AND status = '현행'"
                              ).fetchall():
        st["annex_new"] += guarded(ctx, st, f"admbyl {m['name']}",
                                   lambda m=m: refresh_annexes(ctx, "admrul", m["law_id"], m["name"])) or 0
    st["annex_new"] += refresh_all_law_annexes(ctx, st)
    st["annex_bodies"] = fetch_annex_bodies(ctx, st, ctx.cfg.annex_body_limit)
    return st


def start_sync(conn, kind: str, since: date | None = None) -> int:
    rid = conn.execute("INSERT INTO law.sync_run (kind, since) VALUES (%s, %s) RETURNING id", (kind, since)).fetchone()["id"]
    conn.commit()
    return rid


def finish_sync(conn, run_id: int, st: dict | None, error: str | None = None) -> None:
    conn.rollback()
    errs = (st or {}).get("errors") or []
    status = "failed" if error or errs else "succeeded"
    conn.execute("UPDATE law.sync_run SET finished_at = now(), status = %s, stats = %s, error = %s WHERE id = %s",
                 (status, json.dumps(st or {}, ensure_ascii=False, default=str), error or ("; ".join(errs)[:2000] or None),
                  run_id))
    conn.commit()


def last_success(conn) -> date | None:
    return conn.execute("SELECT max((started_at AT TIME ZONE 'Asia/Seoul')::date) AS d FROM law.sync_run"
                        " WHERE status = 'succeeded' AND kind IN ('daily', 'full')").fetchone()["d"]


def _run(conn, kind: str, since: date | None, body: Callable[[int], dict]) -> dict:
    rid = start_sync(conn, kind, since)
    try:
        st = body(rid)
    except BaseException as e:
        finish_sync(conn, rid, None, f"{type(e).__name__}: {e}"[:2000])
        raise
    finish_sync(conn, rid, st)
    return st | {"run_id": rid}


def run_daily(conn, client, blob, cfg: LawgoConfig, day: date | None = None, check: bool = True) -> dict:
    since = day or last_success(conn)
    if since is None:
        raise LawGoError("법령 미러 최초 적재가 아직 없습니다. 먼저 sync_full(reg law full)을 실행하세요")

    def body(rid: int) -> dict:
        if check:
            canary(client)
        return sync_daily(Ctx(conn, client, blob, cfg, rid), since)
    return _run(conn, "daily", since, body)


def run_full(conn, client, blob, cfg: LawgoConfig, check: bool = True) -> dict:
    def body(rid: int) -> dict:
        if check:
            canary(client)
        return sync_full(Ctx(conn, client, blob, cfg, rid))
    return _run(conn, "full", None, body)


def run_annex(conn, client, blob, cfg: LawgoConfig, limit: int) -> dict:
    def body(rid: int) -> dict:
        st = new_stats()
        st["annex_bodies"] = fetch_annex_bodies(Ctx(conn, client, blob, cfg, rid), st, limit)
        return st
    return _run(conn, "annex", None, body)


def status(conn) -> dict:
    return {
        "masters": conn.execute("SELECT family, status, count(*)::int AS n FROM law.law_master GROUP BY 1, 2"
                                " ORDER BY 1, 2").fetchall(),
        "articles": conn.execute("SELECT count(*)::int AS n FROM law.article WHERE gone_in_mst IS NULL").fetchone()["n"],
        "annex": conn.execute("SELECT count(*)::int AS total, count(html_key)::int AS stored FROM law.annex"
                              " WHERE is_current").fetchone(),
        "catalog": conn.execute("SELECT count(*)::int AS n FROM law.admrul_catalog WHERE status = '현행'").fetchone()["n"],
        "last_success": last_success(conn),
        "recent_runs": conn.execute("SELECT id, kind, status, since, started_at, finished_at, error FROM law.sync_run"
                                    " ORDER BY id DESC LIMIT 5").fetchall(),
    }


# --- 구 감시 수집 (이름 목록 → regulation.law_watch). Task 11에서 CLI와 함께 지운다. ---
SERVICE_URL = "https://www.law.go.kr/DRF/lawService.do?target=law&type=XML&MST={}"


def sync_laws(conn, client: LawGoClient, blob: BlobStore, names: list[str]) -> dict:
    st = {"checked": 0, "fetched": 0, "not_found": []}
    for name in names:
        st["checked"] += 1
        hit = next((r for r in parse_list("law", client.search("law", query=name)).rows
                    if norm_name(r.name) == norm_name(name) and r.status == "현행"), None)
        if hit is None:
            st["not_found"].append(name)
            continue
        w = conn.execute("SELECT last_mst FROM regulation.law_watch WHERE law_id = %s", (hit.law_id,)).fetchone()
        if w and w["last_mst"] == hit.mst:
            conn.execute("UPDATE regulation.law_watch SET last_checked_at = now() WHERE law_id = %s", (hit.law_id,))
            conn.commit()
            continue
        doc = store(conn, blob, source="lawgo", url=SERVICE_URL.format(hit.mst), content=client.service("law", hit.mst),
                    kind=XML, meta={"law_id": hit.law_id, "mst": hit.mst, "name": hit.name})
        conn.execute(
            "INSERT INTO regulation.law_watch (law_id, name, kind, last_mst, promulgated_on, effective_on,"
            " source_document_id, last_checked_at) VALUES (%s,%s,%s,%s,%s,%s,%s, now())"
            " ON CONFLICT (law_id) DO UPDATE SET name = EXCLUDED.name, kind = EXCLUDED.kind,"
            " last_mst = EXCLUDED.last_mst, promulgated_on = EXCLUDED.promulgated_on,"
            " effective_on = EXCLUDED.effective_on, source_document_id = EXCLUDED.source_document_id,"
            " last_checked_at = now()",
            (hit.law_id, hit.name, hit.kind, hit.mst, hit.promulgated_on, hit.effective_on, doc.id))
        if doc.is_new:
            outbox.write(conn, "regulation.law_fetched",
                         {"law_id": hit.law_id, "mst": hit.mst, "name": hit.name, "source_document_id": doc.id})
        st["fetched"] += 1
        conn.commit()
    return st
