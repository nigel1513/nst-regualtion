"""내부규정의 법령 인용 → law 조문 외래키 (spec §3A.5). regulation.reference의 target_law_* 두 열만 쓴다.

- 이름: 정식 명칭 → 약칭 → 정규화(띄어쓰기·가운뎃점). 「같은 법」은 core 추출이 이미 앞 이름으로 바꿔 둔다.
- 조문: 현행 조문. 가장 구체적인 경로부터 맞춘다.
- 법령 폐지·조문 삭제: 외래키는 그대로 두고 REF_LAW_GONE (판정 R3).
- 후보가 여럿: REF_LAW_AMBIGUOUS. 무매칭은 core REFERENCE 검수가 맡는다 (판정 R9).
- core가 내부규정을 다시 처리하면 reference 행이 새로 생긴다. 그래서 이 함수는 매번 전부 다시 맞춘다(멱등).
"""
import json

from reg.core.ingest.loader import norm_title

KINDS = ("REF_LAW_AMBIGUOUS", "REF_LAW_GONE")


def resolve_name(conn, name: str) -> list[str]:
    raw, n = (name or "").strip(), norm_title(name)
    for sql, args in (("SELECT law_id, status FROM law.law_master WHERE name = %s", (raw,)),
                      ("SELECT law_id, status FROM law.law_master WHERE name_abbr = %s", (raw,)),
                      ("SELECT law_id, status FROM law.law_master WHERE name_norm = %s OR abbr_norm = %s", (n, n))):
        hits = conn.execute(sql, args).fetchall()
        if not hits:
            continue
        ids = sorted({h["law_id"] for h in hits})
        current = sorted({h["law_id"] for h in hits if h["status"] == "현행"})
        return current if len(ids) > 1 and len(current) == 1 else ids
    return []


def resolve_article(conn, law_id: str, target_path: str | None) -> dict | None:
    if not target_path:
        return None
    segs = target_path.split(".")
    cands = [".".join(segs[:i]) for i in range(len(segs), 0, -1)]
    return conn.execute("SELECT id, path, deleted, gone_in_mst FROM law.article WHERE law_id = %s AND path = ANY(%s)"
                        " ORDER BY length(path) DESC LIMIT 1", (law_id, cands)).fetchone()


def link_all(conn) -> dict:
    rows = conn.execute(
        "SELECT r.id, r.work_id, r.target_name, r.target_path, r.evidence_text, r.span_start, r.target_law_id,"
        " r.target_law_article_id, pv.path AS source_path,"
        " EXISTS (SELECT 1 FROM regulation.version_provision vp JOIN regulation.work_version v"
        "   ON v.id = vp.work_version_id WHERE vp.provision_version_id = r.source_pv_id"
        "   AND v.version_state = 'CURRENT') AS current"
        " FROM regulation.reference r JOIN regulation.provision_version pv ON pv.id = r.source_pv_id"
        " WHERE r.target_name IS NOT NULL ORDER BY r.id").fetchall()
    status = {r["law_id"]: r["status"] for r in conn.execute("SELECT law_id, status FROM law.law_master").fetchall()}
    names: dict[str, list[str]] = {}
    st = {"refs": len(rows), "linked_law": 0, "linked_article": 0, "ambiguous": 0, "gone": 0, "unmatched": 0,
          "changed": 0}
    tasks: dict[tuple[str, str], tuple[str, dict]] = {}
    for r in rows:
        name = r["target_name"]
        if name not in names:
            names[name] = resolve_name(conn, name)
        ids = names[name]
        law_id = art_id = None
        reason = None
        extra: dict = {}
        if len(ids) == 1:
            law_id = ids[0]
            st["linked_law"] += 1
            if status.get(law_id) == "폐지":
                reason = "law_abolished"
            a = resolve_article(conn, law_id, r["target_path"])
            if a:
                art_id = a["id"]
                st["linked_article"] += 1
                if a["gone_in_mst"] or a["deleted"]:
                    reason = reason or "article_deleted"
            elif r["target_path"]:
                reason = reason or "article_missing"
        elif ids:
            st["ambiguous"] += 1
            extra = {"reason": "multiple", "candidates": ids}
        else:
            st["unmatched"] += 1
        if (law_id, art_id) != (r["target_law_id"], r["target_law_article_id"]):
            conn.execute("UPDATE regulation.reference SET target_law_id = %s, target_law_article_id = %s WHERE id = %s",
                         (law_id, art_id, r["id"]))
            st["changed"] += 1
        if not (r["current"] and r["work_id"].startswith("kr/reg/")):
            continue
        key = f"ref:{r['work_id']}:{r['source_path']}:{r['span_start']}:{name}"
        detail = {"name": name, "evidence": r["evidence_text"], "path": r["source_path"], "target_path": r["target_path"]}
        if reason:
            tasks[("REF_LAW_GONE", key)] = (r["work_id"], detail | {"reason": reason, "law_id": law_id})
            st["gone"] += 1
        elif extra:
            tasks[("REF_LAW_AMBIGUOUS", key)] = (r["work_id"], detail | extra)
    _sync_tasks(conn, tasks)
    return st


def _sync_tasks(conn, tasks: dict[tuple[str, str], tuple[str, dict]]) -> None:
    for (kind, target), (wid, detail) in tasks.items():
        conn.execute(
            "INSERT INTO regulation.review_task AS t (kind, target, work_id, detail) VALUES (%s,%s,%s,%s)"
            " ON CONFLICT (kind, target) DO UPDATE SET detail = EXCLUDED.detail,"
            " status = CASE WHEN t.status = 'RESOLVED' AND NOT coalesce(t.decision ? 'action', false) THEN 'OPEN'"
            "  ELSE t.status END,"  # 사람이 해결한 작업(core.review 결정)은 다시 열지 않는다
            " resolved_at = CASE WHEN t.status = 'RESOLVED' AND NOT coalesce(t.decision ? 'action', false) THEN NULL"
            "  ELSE t.resolved_at END",
            (kind, target, wid, json.dumps(detail, ensure_ascii=False)))
    keys = [f"{k}|{t}" for k, t in tasks]
    conn.execute("UPDATE regulation.review_task SET status = 'RESOLVED', resolved_at = now()"
                 " WHERE kind = ANY(%s) AND status IN ('OPEN', 'HOLD') AND NOT (kind || '|' || target = ANY(%s))",
                 (list(KINDS), keys))
