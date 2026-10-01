"""개정 영향 분석 (spec 9.2): 실질 변경 조항 → Neo4j 역방향 탐색 → change_impact."""
import re

STRONG = {"BASIS", "DELEGATION", "MUTATIS", "IMPLEMENTS"}
SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def severity(change: str, rel: str) -> str:
    if change == "DELETED" or (change == "MODIFIED" and rel in STRONG):
        return "HIGH"
    if change in ("MODIFIED", "RENUMBERED"):
        return "MEDIUM"
    return "LOW"


def _strength(rel: str) -> int:
    return 1 if rel in STRONG else 0


def impact_kind(change: str, rel: str) -> str:
    if change == "DELETED":
        return "참조 대상 삭제"
    if change == "MODIFIED":
        return "근거·위임·준용 대상 개정" if rel in STRONG else "참조 대상 개정"
    if change == "RENUMBERED":
        return "참조 번호 이동"
    return "관련 조문 신설"


def _changes(conn, version_id: str) -> list[dict]:
    """그 버전에서 실질적으로 바뀐 조항. 삭제·번호 이동은 이전 경로가 참조되던 자리다."""
    return conn.execute(
        "SELECT c.kind, c.from_version_id, t.path AS to_path, f.path AS from_path"
        " FROM regulation.provision_change c"
        " LEFT JOIN regulation.provision_version t ON t.id = c.to_pv_id"
        " LEFT JOIN regulation.provision_version f ON f.id = c.from_pv_id"
        " WHERE c.to_version_id = %s AND c.kind <> 'ANNOTATION_ONLY'", (version_id,)).fetchall()


# 1단계: 바뀐 조항(또는 그 조)을 가리키는 다른 규범문서의 조항 — 대상 노드에서 출발해 인덱스를 탄다
Q1 = ("UNWIND $causes AS c MATCH (t:RegProvision {key: c.key})<-[r]-(src:RegProvision)"
      " WHERE type(r) IN $rels AND src.work_id <> c.work"
      " RETURN DISTINCT t.path AS cause_path, c.kind AS change, src.work_id AS work_id, src.path AS path,"
      " type(r) AS rel, r.evidence AS evidence")
# 신설: 규범문서 전체를 가리키는 참조만, 버전당 원인 하나로 묶는다
Q1_ADDED = ("MATCH (t:RegWork {work_id: $work})<-[r]-(src:RegProvision) WHERE type(r) IN $rels AND src.work_id <> $work"
            " RETURN DISTINCT $path AS cause_path, 'ADDED' AS change, src.work_id AS work_id, src.path AS path,"
            " type(r) AS rel, r.evidence AS evidence")
# 2단계: 1단계 규정(또는 그 조)에 위임·시행 관계로 기댄 또 다른 규정의 조항
Q2 = ("UNWIND $first AS f MATCH (:RegWork {work_id: f.work_id})<-[r:DELEGATION|IMPLEMENTS]-(src:RegProvision)"
      " WHERE src.work_id <> f.work_id AND src.work_id <> $cause_work"
      " RETURN f.cause_path AS cause_path, f.change AS change, src.work_id AS work_id, src.path AS path,"
      " type(r) AS rel, r.evidence AS evidence"
      " UNION UNWIND $first AS f"
      " MATCH (:RegProvision {key: f.work_id + '|' + split(f.path, '.')[0]})<-[r:DELEGATION|IMPLEMENTS]-(src:RegProvision)"
      " WHERE src.work_id <> f.work_id AND src.work_id <> $cause_work"
      " RETURN f.cause_path AS cause_path, f.change AS change, src.work_id AS work_id, src.path AS path,"
      " type(r) AS rel, r.evidence AS evidence")
RELS = ["BASIS", "DELEGATION", "IMPLEMENTS", "MUTATIS", "EXCEPTION", "CITATION"]


def analyze_version(conn, driver, work_id: str, version_id: str) -> list[dict]:
    changes = _changes(conn, version_id)
    if not changes:
        return []
    causes, added = [], []
    for ch in changes:
        path = ch["from_path"] if ch["kind"] in ("DELETED", "RENUMBERED") else ch["to_path"]
        if not path:
            continue
        if ch["kind"] == "ADDED":
            if re.fullmatch(r"a\d+(?:-\d+)?", path):  # 본문 조만 (항·호는 그 조에 포함, 부칙·별표·서식 신설은 개정마다 생긴다)
                added.append(path)
            continue
        parts = path.split(".")
        for key_path in (".".join(parts[:i]) for i in range(len(parts), 0, -1)):  # 그 조항과 상위 항·조
            causes.append({"key": f"{work_id}|{key_path}", "work": work_id, "path": path, "kind": ch["kind"]})
    from_version = next((c["from_version_id"] for c in changes if c["from_version_id"]), None)
    with driver.session() as s:
        first = [{**dict(r), "hops": 1} for r in s.run(Q1, causes=causes, rels=RELS)] if causes else []
        if added:
            added.sort(key=lambda p: [int(x) if x.isdigit() else x for x in re.findall(r"\d+|\D+", p)])
            label = ", ".join(added[:5]) + (f" 외 {len(added) - 5}" if len(added) > 5 else "")
            first += [{**dict(r), "hops": 1} for r in s.run(Q1_ADDED, work=work_id, path=label, rels=RELS)]
        second = [{**dict(r), "hops": 2} for r in s.run(Q2, first=first, cause_work=work_id)] if first else []
    # 참조가 가리키는 단위(t.path)마다 하나로: 그 아래 여러 조항이 바뀌면 가장 무거운 변경으로 묶는다
    rank = {"DELETED": 0, "MODIFIED": 1, "RENUMBERED": 2, "ADDED": 3}
    merged: dict[tuple, dict] = {}
    for f in first + second:
        k = (f["cause_path"], f["work_id"], f["path"], f["hops"])
        cur = merged.get(k)
        if cur is None or (rank[f["change"]], -_strength(f["rel"])) < (rank[cur["change"]], -_strength(cur["rel"])):
            merged[k] = f
    out = []
    for f in merged.values():
        cur = conn.execute("SELECT id FROM regulation.work_version WHERE work_id = %s AND version_state = 'CURRENT'",
                           (f["work_id"],)).fetchone()
        row = conn.execute(
            "INSERT INTO regulation.change_impact (cause_work_id, cause_version_id, cause_from_version_id, cause_path,"
            " cause_change, affected_work_id, affected_version_id, affected_path, rel_type, evidence, impact_kind,"
            " severity, hops) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING *",
            (work_id, version_id, from_version, f["cause_path"], f["change"], f["work_id"], cur["id"] if cur else None,
             f["path"], f["rel"], f["evidence"], impact_kind(f["change"], f["rel"]), severity(f["change"], f["rel"]),
             f["hops"])).fetchone()
        if row:
            out.append(row)
    conn.commit()
    return sorted(out, key=lambda r: (SEVERITY_ORDER[r["severity"]], r["affected_work_id"], r["affected_path"]))
