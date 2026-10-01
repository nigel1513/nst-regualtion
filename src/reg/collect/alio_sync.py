import json
from pathlib import Path

import yaml

from reg import outbox
from reg.collect.alio import AlioClient, RuleDetail
from reg.collect.archive import store
from reg.collect.sniff import sniff
from reg.storage.blob import BlobStore

DOWNLOAD_URL = "https://www.alio.go.kr/download/rulefiledown.json?fileNo={}"


def load_institutions(conn, path: Path) -> list[dict]:
    for i in yaml.safe_load(Path(path).read_text(encoding="utf-8")):
        conn.execute(
            "INSERT INTO regulation.institution (code, name, kind, alio_apba_id, alio_name)"
            " VALUES (%(code)s, %(name)s, %(kind)s, %(alio_apba_id)s, %(alio_name)s)"
            " ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, kind = EXCLUDED.kind,"
            " alio_apba_id = EXCLUDED.alio_apba_id, alio_name = EXCLUDED.alio_name", i)
    conn.commit()
    return conn.execute("SELECT * FROM regulation.institution WHERE active ORDER BY id").fetchall()


def _upsert_rule(conn, inst_id: int, d: RuleDetail, fingerprint: str) -> None:
    conn.execute(
        "INSERT INTO regulation.alio_rule (seq, institution_id, title, divis, revised_on, posted_on,"
        " list_fingerprint, detail) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)"
        " ON CONFLICT (seq) DO UPDATE SET title = EXCLUDED.title, divis = EXCLUDED.divis,"
        " revised_on = EXCLUDED.revised_on, posted_on = EXCLUDED.posted_on,"
        " list_fingerprint = EXCLUDED.list_fingerprint, detail = EXCLUDED.detail, last_seen_at = now()",
        (d.seq, inst_id, d.title, d.divis, d.revised_on, d.posted_on, fingerprint,
         json.dumps(d.raw, ensure_ascii=False)))


def sync_institution(conn, alio: AlioClient, blob: BlobStore, inst: dict, limit: int | None = None) -> dict:
    st = dict(rules_seen=0, details_fetched=0, files_fetched=0, files_new_content=0, files_rejected=0)
    for row in alio.list_rules(inst["alio_name"], inst["alio_apba_id"]):
        if limit is not None and st["rules_seen"] >= limit:
            break
        st["rules_seen"] += 1
        known = conn.execute(
            "SELECT r.list_fingerprint, (SELECT count(*) FROM regulation.alio_rule_file f WHERE f.seq = r.seq) AS nfiles"
            " FROM regulation.alio_rule r WHERE r.seq = %s", (row.seq,)).fetchone()
        if known and known["list_fingerprint"] == row.fingerprint and known["nfiles"] > 0:
            conn.execute("UPDATE regulation.alio_rule SET last_seen_at = now() WHERE seq = %s", (row.seq,))
            conn.commit()
            continue
        d = alio.detail(row.seq)
        st["details_fetched"] += 1
        _upsert_rule(conn, inst["id"], d, row.fingerprint)
        have = {r["file_no"] for r in conn.execute(
            "SELECT file_no FROM regulation.alio_rule_file WHERE seq = %s", (row.seq,)).fetchall()}
        for ord_, (file_no, name) in enumerate(d.files):
            if file_no in have:
                continue
            content = alio.download(file_no)
            st["files_fetched"] += 1
            kind = sniff(content, name)
            if kind is None:
                st["files_rejected"] += 1
                conn.execute("INSERT INTO regulation.alio_rule_file (file_no, seq, file_name, ord, status,"
                             " reject_reason) VALUES (%s,%s,%s,%s,'rejected',%s)",
                             (file_no, row.seq, name, ord_, f"형식 불명 ({content[:16]!r})"))
                continue
            doc = store(conn, blob, source="alio", url=DOWNLOAD_URL.format(file_no), content=content,
                        kind=kind, meta={"seq": row.seq, "file_no": file_no, "file_name": name,
                                         "institution_code": inst["code"]})
            conn.execute("INSERT INTO regulation.alio_rule_file (file_no, seq, file_name, ord, status,"
                         " source_document_id) VALUES (%s,%s,%s,%s,'fetched',%s)",
                         (file_no, row.seq, name, ord_, doc.id))
            if doc.is_new:
                st["files_new_content"] += 1
                outbox.write(conn, "regulation.source_fetched", {
                    "source": "alio", "source_document_id": doc.id, "institution_code": inst["code"],
                    "seq": row.seq, "file_no": file_no, "file_name": name})
        conn.commit()  # 규정 단위 커밋: 중간에 멈춰도 다시 실행하면 이어서 받는다
    return st
