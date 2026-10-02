"""품질 검사와 검수 큐 기록 (spec 6.5)."""
import json
import re
from dataclasses import dataclass, field

from reg.core.effective import Effective
from reg.core.model import ParsedDoc

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
    """현행 버전의 미해석 외부 참조마다 검수 작업 하나. 참조 id는 재처리 때 바뀌므로 내용으로 키를 만든다."""
    rows = conn.execute(
        "SELECT DISTINCT pv.path, r.span_start, r.target_name, r.evidence_text FROM regulation.reference r"
        " JOIN regulation.provision_version pv ON pv.id = r.source_pv_id"
        " JOIN regulation.version_provision vp ON vp.provision_version_id = pv.id"
        " JOIN regulation.work_version v ON v.id = vp.work_version_id AND v.version_state = 'CURRENT'"
        " WHERE r.work_id = %s AND r.target_kind = 'EXTERNAL_UNRESOLVED'", (work_id,)).fetchall()
    keys = []
    for r in rows:
        key = f"ref:{work_id}:{r['path']}:{r['span_start']}:{r['target_name']}"
        keys.append(key)
        conn.execute("INSERT INTO regulation.review_task (kind, target, work_id, detail) VALUES ('REFERENCE', %s, %s, %s)"
                     " ON CONFLICT (kind, target) DO NOTHING",
                     (key, work_id, json.dumps({"name": r["target_name"], "evidence": r["evidence_text"],
                                                "path": r["path"]}, ensure_ascii=False)))
    conn.execute("UPDATE regulation.review_task SET status = 'RESOLVED', resolved_at = now() WHERE kind = 'REFERENCE'"
                 " AND work_id = %s AND status = 'OPEN' AND NOT (target = ANY(%s))", (work_id, keys))
    return len(rows)
