"""outbox 소비자: 수집 이벤트 → 추출 → 파싱 → 시행일 판정 → 적재."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from reg.core.ingest import registry
from reg.core.ingest.loader import add_version, rebuild_work, upsert_work
from reg.core.quality import check, record, record_reference_tasks
from reg.core.refs import resolve_and_store
from reg.platform import outbox
from reg.platform.convert import Converter
from reg.platform.storage.blob import BlobStore

MAX_ATTEMPTS = 3
STRUCTURE_TABLES = ["reference", "review_task", "provision_change", "version_provision", "provision_version",
                    "provision", "amendment_history", "work_version", "work"]


def _topics() -> list[str]:
    return list(registry.handlers())


def _check_unhandled(conn) -> None:
    """등록되지 않은 수집 주제의 대기 이벤트가 있으면 조용히 쌓이지 않게 멈춘다."""
    row = conn.execute("SELECT topic FROM ops.outbox WHERE processed_at IS NULL AND attempts < %s"
                       " AND topic LIKE 'regulation.%%fetched' AND NOT (topic = ANY(%s)) LIMIT 1",
                       (MAX_ATTEMPTS, _topics())).fetchone()
    if row:
        raise RuntimeError(f"처리기가 등록되지 않은 주제: {row['topic']} (reg.wiring.register_sources() 필요)")


def _load(conn, pv) -> tuple:
    """출처가 만든 판본을 적재한다 (규범문서 등록 + 버전 추가)."""
    upsert_work(conn, pv.work_id, pv.work_kind, pv.title, pv.institution_id, pv.external_ids)
    vid = add_version(conn, pv.work_id, pv.source_document_id, pv.doc, pv.effective, posted_on=pv.posted_on)
    return pv.work_id, vid, pv.doc, pv.effective


def rebuild_all(conn) -> int:
    conn.execute("TRUNCATE " + ", ".join(f"regulation.{t}" for t in STRUCTURE_TABLES) + " CASCADE")
    n = conn.execute("UPDATE ops.outbox SET processed_at = NULL, attempts = 0, last_error = NULL"
                     " WHERE topic = ANY(%s)", (_topics(),)).rowcount
    conn.commit()
    return n


def emit_version_events(conn, work_id: str) -> int:
    """이번 트랜잭션에서 더한 버전 중 기존 버전들보다 시행일이 늦은 것마다 regulation.version_loaded를 남긴다.

    처음 적재(기존 버전 없음)나 과거 버전의 뒤늦은 수집은 개정이 아니므로 남기지 않는다. 묶음 처리는 한 트랜잭션이라
    created_at = now()이면 이번 묶음에서 더한 버전이다."""
    rows = conn.execute("SELECT id, effective_from, created_at = now() AS new FROM regulation.work_version"
                        " WHERE work_id = %s", (work_id,)).fetchall()
    old = [r["effective_from"] for r in rows if not r["new"]]
    if not old:
        return 0
    latest = max((d for d in old if d), default=date.min)
    n = 0
    for r in sorted((r for r in rows if r["new"] and r["effective_from"] and r["effective_from"] > latest),
                    key=lambda r: r["effective_from"]):
        outbox.write(conn, "regulation.version_loaded", {"work_id": work_id, "version_id": r["id"]})
        n += 1
    return n


def kst_today() -> date:
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def _fail(conn, ev: dict, e: Exception, st: dict) -> None:
    conn.execute("UPDATE ops.outbox SET attempts = attempts + 1, claimed_at = now(), last_error = %s"
                 " WHERE id = %s", (f"{type(e).__name__}: {e}"[:2000], ev["id"]))
    st["failed"] += 1
    if ev["attempts"] + 1 >= MAX_ATTEMPTS:
        st["parked"] += 1


def process_once(conn, blob: BlobStore, limit: int = 100, today: date | None = None,
                 converter: Converter | None = None) -> dict:
    """같은 규정의 대기 이벤트를 한 묶음으로 처리한다: 버전을 모두 더한 뒤 계보·참조·품질을 한 번만 계산.

    묶음마다 커밋하고, 규정 단위 advisory lock으로 여러 작업자가 동시에 돌아도 같은 규정은 한 작업자만 맡는다.
    """
    today = today or kst_today()
    _check_unhandled(conn)
    handlers = registry.handlers()
    st = {"claimed": 0, "ok": 0, "failed": 0, "parked": 0}
    q = ("SELECT id, topic, payload, attempts FROM ops.outbox WHERE processed_at IS NULL AND attempts < %s"
         " AND topic = ANY(%s)")
    while st["claimed"] < limit:
        first = conn.execute(q + " ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED",
                             (MAX_ATTEMPTS, _topics())).fetchone()
        if first is None:
            break
        field = handlers[first["topic"]].group_field
        key = first["payload"].get(field)
        group = [first] + (conn.execute(
            q + " AND topic = %s AND payload->>%s = %s AND id <> %s ORDER BY id FOR UPDATE SKIP LOCKED",
            (MAX_ATTEMPTS, _topics(), first["topic"], field, key, first["id"])).fetchall() if key else [])
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{first['topic']}:{key}",))
        st["claimed"] += len(group)
        done = []
        for ev in group:
            try:
                with conn.transaction():
                    pv = handlers[ev["topic"]].prepare(conn, blob, ev["payload"], today, converter)
                    done.append((ev, _load(conn, pv) if pv is not None else None))
            except Exception as e:  # 파일 하나의 실패가 묶음을 멈추지 않게
                _fail(conn, ev, e, st)
        skipped = [ev for ev, r in done if r is None]
        done = [(ev, r) for ev, r in done if r is not None]
        for ev in skipped:
            conn.execute("UPDATE ops.outbox SET processed_at = now(), claimed_at = now(), last_error = NULL"
                         " WHERE id = %s", (ev["id"],))
            st["ok"] += 1
        if done:
            try:
                with conn.transaction():
                    for wid in dict.fromkeys(r[0] for _, r in done):
                        rebuild_work(conn, wid, today)
                        resolve_and_store(conn, wid)
                        record_reference_tasks(conn, wid)
                        emit_version_events(conn, wid)
                    for ev, (wid, vid, doc, eff) in done:
                        record(conn, wid, vid, check(doc, eff))
                        conn.execute("UPDATE ops.outbox SET processed_at = now(), claimed_at = now(),"
                                     " last_error = NULL WHERE id = %s", (ev["id"],))
                st["ok"] += len(done)
            except Exception as e:
                for ev, _ in done:
                    _fail(conn, ev, e, st)
        conn.commit()
    return st
