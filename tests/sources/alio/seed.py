"""폐지 대조 테스트용 최소 적재: 수집·처리 없이 표만 채운다."""
import json
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
T0 = datetime(2026, 10, 2, 2, 0, tzinfo=KST)   # 1일차 배치 시작 02:00 KST


def add_inst(conn, code: str = "KASI", apba: str | None = "C0266", active: bool = True) -> int:
    row = conn.execute(
        "INSERT INTO regulation.institution (code, name, kind, alio_apba_id, alio_name, active)"
        " VALUES (%s, %s, 'GRI', %s, %s, %s) RETURNING id", (code, code, apba, code, active)).fetchone()
    conn.commit()
    return row["id"]


def add_rule(conn, inst_id: int, seq: str, seen: datetime, work: bool = True) -> str | None:
    conn.execute("INSERT INTO regulation.alio_rule (seq, institution_id, title, last_seen_at) VALUES (%s,%s,%s,%s)",
                 (seq, inst_id, f"규정{seq}", seen))
    wid = None
    if work:
        wid = f"kr/reg/T/규정{seq}"
        conn.execute("INSERT INTO regulation.work (id, kind, institution_id, title, external_ids)"
                     " VALUES (%s, 'INTERNAL_REG', %s, %s, %s)",
                     (wid, inst_id, f"규정{seq}", json.dumps({"alio_seq": seq})))
    conn.commit()
    return wid


def see(conn, seq: str, at: datetime) -> None:
    conn.execute("UPDATE regulation.alio_rule SET last_seen_at = %s WHERE seq = %s", (at, seq))
    conn.commit()


def rule(conn, seq: str) -> dict:
    return conn.execute("SELECT * FROM regulation.alio_rule WHERE seq = %s", (seq,)).fetchone()


def work(conn, wid: str) -> dict:
    return conn.execute("SELECT status, abolished_on FROM regulation.work WHERE id = %s", (wid,)).fetchone()


def task(conn, wid: str) -> dict | None:
    return conn.execute("SELECT status, detail, decision FROM regulation.review_task"
                        " WHERE kind = 'ABOLISHED' AND target = %s", (f"work:{wid}",)).fetchone()
