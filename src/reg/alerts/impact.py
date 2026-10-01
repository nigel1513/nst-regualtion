"""개정 영향 분석 (spec 9.2): 실질 변경 조항 → Neo4j 역방향 탐색 → change_impact."""
STRONG = {"BASIS", "DELEGATION", "MUTATIS", "IMPLEMENTS"}
SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def severity(change: str, rel: str) -> str:
    if change == "DELETED" or (change == "MODIFIED" and rel in STRONG):
        return "HIGH"
    if change in ("MODIFIED", "RENUMBERED"):
        return "MEDIUM"
    return "LOW"


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


# 1단계: 바뀐 조항(또는 그 조)을 가리키는 다른 규범문서의 조항. 신설(ADDED)은 규범문서 전체를 가리키는 참조만
Q1 = ("UNWIND $causes AS c MATCH (src:RegProvision)-[r]->(t)"
      " WHERE type(r) IN $rels AND src.work_id <> c.work"
      " AND ((t:RegProvision AND t.key = c.key AND c.kind <> 'ADDED') OR (t:RegWork AND t.work_id = c.work AND c.kind = 'ADDED'))"
      " RETURN DISTINCT c.path AS cause_path, c.kind AS change, src.work_id AS work_id, src.path AS path,"
      " type(r) AS rel, r.evidence AS evidence")
# 2단계: 1단계 규정(또는 그 조)에 위임·시행 관계로 기댄 또 다른 규정의 조항
Q2 = ("UNWIND $first AS f MATCH (src:RegProvision)-[r:DELEGATION|IMPLEMENTS]->(t)"
      " WHERE src.work_id <> f.work_id AND src.work_id <> $cause_work"
      " AND ((t:RegWork AND t.work_id = f.work_id)"
      "  OR (t:RegProvision AND t.work_id = f.work_id AND split(t.path, '.')[0] = split(f.path, '.')[0]))"
      " RETURN DISTINCT f.cause_path AS cause_path, f.change AS change, src.work_id AS work_id, src.path AS path,"
      " type(r) AS rel, r.evidence AS evidence")
RELS = ["BASIS", "DELEGATION", "IMPLEMENTS", "MUTATIS", "EXCEPTION", "CITATION"]


def analyze_version(conn, driver, work_id: str, version_id: str) -> list[dict]:
    changes = _changes(conn, version_id)
    if not changes:
        return []
    causes = []
    for ch in changes:
        path = ch["from_path"] if ch["kind"] in ("DELETED", "RENUMBERED") else ch["to_path"]
        if not path:
            continue
        for key_path in dict.fromkeys([path, path.split(".")[0]]):
            causes.append({"key": f"{work_id}|{key_path}", "work": work_id, "path": path, "kind": ch["kind"]})
    from_version = next((c["from_version_id"] for c in changes if c["from_version_id"]), None)
    with driver.session() as s:
        first = [{**dict(r), "hops": 1} for r in s.run(Q1, causes=causes, rels=RELS)]
        second = [{**dict(r), "hops": 2} for r in s.run(Q2, first=first, cause_work=work_id)] if first else []
    out = []
    for f in first + second:
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
