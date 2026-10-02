import json
from pathlib import Path

import yaml

from reg.platform import outbox
from reg.platform.archive import store
from reg.platform.sniff import sniff
from reg.platform.storage.blob import BlobStore
from reg.sources.alio.client import AlioClient, RuleDetail

DOWNLOAD_URL = "https://www.alio.go.kr/download/rulefiledown.json?fileNo={}"


def load_institutions(conn, path: Path) -> list[dict]:
    """YAML 기관 목록을 DB에 반영한다. active가 없으면 true, aliases(약칭)가 없으면 [].

    반환: 일 배치 대상(active이고 ALIO id가 있음)."""
    for i in yaml.safe_load(Path(path).read_text(encoding="utf-8")):
        conn.execute(
            "INSERT INTO regulation.institution (code, name, kind, alio_apba_id, alio_name, active, aliases)"
            " VALUES (%(code)s, %(name)s, %(kind)s, %(alio_apba_id)s, %(alio_name)s, %(active)s, %(aliases)s)"
            " ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, kind = EXCLUDED.kind,"
            " alio_apba_id = EXCLUDED.alio_apba_id, alio_name = EXCLUDED.alio_name, active = EXCLUDED.active,"
            " aliases = EXCLUDED.aliases",
            {"alio_apba_id": None, "alio_name": None, "active": True, **i, "aliases": list(i.get("aliases") or [])})
    conn.commit()
    return conn.execute("SELECT * FROM regulation.institution WHERE active AND alio_apba_id IS NOT NULL"
                        " ORDER BY id").fetchall()


def get_institution(conn, code: str) -> dict | None:
    """활성 여부와 상관없이 기관 하나 (backfill용)."""
    return conn.execute("SELECT * FROM regulation.institution WHERE code = %s", (code,)).fetchone()


def _upsert_rule(conn, inst_id: int, d: RuleDetail, fingerprint: str) -> None:
    conn.execute(
        "INSERT INTO regulation.alio_rule (seq, institution_id, title, divis, revised_on, posted_on,"
        " list_fingerprint, detail) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)"
        " ON CONFLICT (seq) DO UPDATE SET title = EXCLUDED.title, divis = EXCLUDED.divis,"
        " revised_on = EXCLUDED.revised_on, posted_on = EXCLUDED.posted_on,"
        " list_fingerprint = EXCLUDED.list_fingerprint, detail = EXCLUDED.detail, last_seen_at = now()",
        (d.seq, inst_id, d.title, d.divis, d.revised_on, d.posted_on, fingerprint,
         json.dumps(d.raw, ensure_ascii=False)))


def _record_file(conn, file_no, seq, name, ord_, status, reason, doc_id) -> None:
    """거부됐던 fileNo는 재시도 결과로 덮어쓴다. 이미 받은 fileNo는 건드리지 않는다."""
    conn.execute(
        "INSERT INTO regulation.alio_rule_file (file_no, seq, file_name, ord, status, reject_reason,"
        " source_document_id) VALUES (%s,%s,%s,%s,%s,%s,%s)"
        " ON CONFLICT (file_no) DO UPDATE SET seq = EXCLUDED.seq, file_name = EXCLUDED.file_name,"
        " ord = EXCLUDED.ord, status = EXCLUDED.status, reject_reason = EXCLUDED.reject_reason,"
        " source_document_id = EXCLUDED.source_document_id, fetched_at = now()"
        " WHERE regulation.alio_rule_file.status = 'rejected'",
        (file_no, seq, name, ord_, status, reason, doc_id))


def sync_institution(conn, alio: AlioClient, blob: BlobStore, inst: dict, limit: int | None = None) -> dict:
    """한 기관의 목록 전체를 돈다.

    complete=True는 상한(limit) 없이 목록 끝까지 예외 없이 돈 경우뿐이다. 폐지 대조(reconcile)의 전제다.
    started_at은 DB now()다. 이 실행이 본 규정의 last_seen_at(now(), 같거나 뒤의 트랜잭션)은 모두 started_at 이상이다.
    """
    started = conn.execute("SELECT now() AS t").fetchone()["t"]
    conn.commit()   # now()는 트랜잭션 시작 시각: 여기서 끝내야 뒤 규정들의 now()가 이보다 앞서지 않는다
    st = dict(rules_seen=0, details_fetched=0, files_fetched=0, files_new_content=0, files_rejected=0,
              complete=False, started_at=started.isoformat())
    for row in alio.list_rules(inst["alio_name"], inst["alio_apba_id"]):
        if limit is not None and st["rules_seen"] >= limit:
            break
        st["rules_seen"] += 1
        known = conn.execute(
            "SELECT r.list_fingerprint, (SELECT count(*) FROM regulation.alio_rule_file f"
            " WHERE f.seq = r.seq AND f.status = 'fetched') AS nfiles"
            " FROM regulation.alio_rule r WHERE r.seq = %s", (row.seq,)).fetchone()
        if known and known["list_fingerprint"] == row.fingerprint and known["nfiles"] > 0:
            conn.execute("UPDATE regulation.alio_rule SET last_seen_at = now() WHERE seq = %s", (row.seq,))
            conn.commit()
            continue
        d = alio.detail(row.seq)
        st["details_fetched"] += 1
        _upsert_rule(conn, inst["id"], d, row.fingerprint)
        have = {r["file_no"] for r in conn.execute(  # 다른 규정에 이미 받은 fileNo도 다시 받지 않는다
            "SELECT file_no FROM regulation.alio_rule_file WHERE status = 'fetched' AND file_no = ANY(%s)",
            ([f for f, _ in d.files],)).fetchall()}
        for ord_, (file_no, name) in enumerate(d.files):
            if file_no in have:
                continue
            have.add(file_no)  # 같은 bFiles 안의 중복 fileNo
            content = alio.download(file_no)
            st["files_fetched"] += 1
            kind = sniff(content, name)
            if kind is None:
                st["files_rejected"] += 1
                _record_file(conn, file_no, row.seq, name, ord_, "rejected", f"형식 불명 ({content[:16]!r})", None)
                continue
            doc = store(conn, blob, source="alio", url=DOWNLOAD_URL.format(file_no), content=content,
                        kind=kind, meta={"seq": row.seq, "file_no": file_no, "file_name": name,
                                         "institution_code": inst["code"], "institution_name": inst["name"]})
            _record_file(conn, file_no, row.seq, name, ord_, "fetched", None, doc.id)
            if doc.is_new:
                st["files_new_content"] += 1
                outbox.write(conn, "regulation.source_fetched", {
                    "source": "alio", "source_document_id": doc.id, "institution_code": inst["code"],
                    "seq": row.seq, "file_no": file_no, "file_name": name})
        conn.commit()  # 규정 단위 커밋: 중간에 멈춰도 다시 실행하면 이어서 받는다
    else:
        st["complete"] = limit is None
    return st
