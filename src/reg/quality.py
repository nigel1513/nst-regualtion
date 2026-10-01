"""품질 검사와 검수 큐 기록 (spec 6.5)."""
import json
import re
from dataclasses import dataclass, field

from reg.structure.effective import Effective
from reg.structure.model import ParsedDoc

BLOCKING = {"PARSE", "CONFLICT", "LOW_TEXT"}


@dataclass
class Issue:
    kind: str
    detail: dict = field(default_factory=dict)


def check(doc: ParsedDoc, eff: Effective) -> list[Issue]:
    out = []
    if eff.status == "CONFLICT":
        out.append(Issue("CONFLICT", {"basis": eff.basis}))
    elif eff.status == "UNCERTAIN":
        out.append(Issue("EFFECTIVE_DATE", {"basis": eff.basis}))
    arts = [p for p in doc.provisions if p.unit == "article"]
    if not arts or sum(len(p.text) for p in arts) / len(arts) < 10 and not all(p.deleted for p in arts):
        out.append(Issue("LOW_TEXT", {"articles": len(arts)}))
        return out
    nums = {int(m[1]) for p in arts if (m := re.fullmatch(r"a(\d+)(?:~\d+)?", p.path))}
    missing = sorted(set(range(1, max(nums) + 1)) - nums) if nums else []
    if missing:
        out.append(Issue("PARSE", {"check": "gap", "missing": missing[:20]}))
    toc = doc.meta.get("toc")
    if toc:
        body = {p.path for p in arts}
        diff = sorted(set(toc) ^ body)
        if diff:
            out.append(Issue("PARSE", {"check": "toc", "diff": diff[:20]}))
    return out


def record(conn, work_id: str, version_id: str, issues: list[Issue]) -> str:
    kinds = set()
    for i in issues:
        conn.execute("INSERT INTO regulation.review_task (kind, target, work_id, detail) VALUES (%s,%s,%s,%s)"
                     " ON CONFLICT (kind, target) DO UPDATE SET detail = EXCLUDED.detail",
                     (i.kind, version_id, work_id, json.dumps(i.detail, ensure_ascii=False)))
        kinds.add(i.kind)
    conn.execute("UPDATE regulation.review_task SET status = 'RESOLVED', resolved_at = now()"
                 " WHERE target = %s AND status = 'OPEN' AND NOT (kind = ANY(%s))", (version_id, list(kinds)))
    status = "REVIEW" if kinds & BLOCKING else "PASSED"
    conn.execute("UPDATE regulation.work_version SET validation_status = %s WHERE id = %s", (status, version_id))
    return status


def record_reference_tasks(conn, work_id: str) -> int:
    rows = conn.execute("SELECT id, target_name, evidence_text FROM regulation.reference WHERE work_id = %s"
                        " AND target_kind = 'EXTERNAL_UNRESOLVED'", (work_id,)).fetchall()
    for r in rows:
        conn.execute("INSERT INTO regulation.review_task (kind, target, work_id, detail) VALUES ('REFERENCE', %s, %s, %s)"
                     " ON CONFLICT (kind, target) DO NOTHING",
                     (f"ref:{r['id']}", work_id, json.dumps({"name": r["target_name"], "evidence": r["evidence_text"]},
                                                           ensure_ascii=False)))
    return len(rows)
