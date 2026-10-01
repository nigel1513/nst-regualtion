"""개정 영향 분석 (spec 9.2): 실질 변경 조항 → Neo4j 역방향 탐색 → change_impact."""
import re

STRONG = {"BASIS", "DELEGATION", "MUTATIS", "IMPLEMENTS"}
SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def severity(change: str, rel: str, whole: bool = False) -> str:
    """spec 9.2-3. 규범문서 전체를 가리키는 참조(whole)는 어느 조가 바뀌었는지 특정되지 않아 한 단계 낮춘다."""
    if whole:
        return "MEDIUM" if change != "ADDED" and rel in STRONG else "LOW"
    if change == "DELETED" or (change == "MODIFIED" and rel in STRONG):
        return "HIGH"
    if change in ("MODIFIED", "RENUMBERED"):
        return "MEDIUM"
    return "LOW"


def _strength(rel: str) -> int:
    return 1 if rel in STRONG else 0


def impact_kind(change: str, rel: str, whole: bool = False) -> str:
    if whole and change != "ADDED":
        return "참조 규범문서 개정"
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
# 규범문서 전체를 가리키는 참조: 버전당 원인 하나 (어느 조든 바뀌면 검토 대상, spec 9.2-2)
Q1_WORK = ("MATCH (t:RegWork {work_id: $work})<-[r]-(src:RegProvision) WHERE type(r) IN $rels AND src.work_id <> $work"
           " RETURN DISTINCT $path AS cause_path, $kind AS change, src.work_id AS work_id, src.path AS path,"
           " type(r) AS rel, r.evidence AS evidence, true AS whole")
# 2단계: 1단계에서 강한 관계(근거·위임·준용·시행)로 영향받은 조항(또는 그 상위 항·조)을 위임·시행 관계로 가리키는 조항
Q2 = ("UNWIND $first AS f UNWIND f.keys AS k MATCH (:RegProvision {key: k})<-[r:DELEGATION|IMPLEMENTS]-(src:RegProvision)"
      " WHERE src.work_id <> f.work_id AND src.work_id <> $cause_work"
      " RETURN DISTINCT f.cause_path AS cause_path, f.change AS change, f.sev AS cap, src.work_id AS work_id,"
      " src.path AS path, type(r) AS rel, r.evidence AS evidence")
RELS = ["BASIS", "DELEGATION", "IMPLEMENTS", "MUTATIS", "EXCEPTION", "CITATION"]


def _natural(p: str) -> list:
    return [int(x) if x.isdigit() else x for x in re.findall(r"\d+|\D+", p)]


def _label(paths) -> str:
    ps = sorted(set(paths), key=_natural)
    return ", ".join(ps[:5]) + (f" 외 {len(ps) - 5}" if len(ps) > 5 else "")


def _ancestors(path: str) -> list[str]:
    parts = path.split(".")
    return [".".join(parts[:i]) for i in range(len(parts), 0, -1)]


def analyze_version(conn, driver, work_id: str, version_id: str, status: str = "NEW",
                    note: str | None = None) -> list[dict]:
    """status/note: 사후 검증(backtest)은 처음부터 RESOLVED로 넣어 알림 경로에 한 순간도 걸리지 않게 한다."""
    changes = _changes(conn, version_id)
    if not changes:
        return []
    rank = {"DELETED": 0, "MODIFIED": 1, "RENUMBERED": 2, "ADDED": 3}
    causes, added, touched = [], [], []
    for ch in changes:
        path = ch["from_path"] if ch["kind"] in ("DELETED", "RENUMBERED") else ch["to_path"]
        if not path:
            continue
        body = re.fullmatch(r"a\d+(?:-\d+)?", path.split(".")[0])  # 본문 조 (부칙·별표·서식 신설은 개정마다 생긴다)
        if ch["kind"] == "ADDED":
            if body and "." not in path:
                added.append(path)
            continue
        if body:
            touched.append((rank[ch["kind"]], ch["kind"], path.split(".")[0]))
        for key_path in _ancestors(path):  # 그 조항과 상위 항·조
            causes.append({"key": f"{work_id}|{key_path}", "work": work_id, "path": path, "kind": ch["kind"]})
    from_version = next((c["from_version_id"] for c in changes if c["from_version_id"]), None)
    with driver.session() as s:
        if not s.run("MATCH (w:RegWork {work_id: $w}) RETURN count(w) AS n", w=work_id).single()["n"]:
            raise LookupError(f"그래프에 {work_id}가 없습니다 (reg graph sync 필요)")
        first = [{**dict(r), "hops": 1, "whole": False} for r in s.run(Q1, causes=causes, rels=RELS)] if causes else []
        if touched:
            kind = min(touched)[1]
            first += [{**dict(r), "hops": 1} for r in s.run(Q1_WORK, work=work_id, kind=kind, rels=RELS,
                                                              path=_label(p for _, _, p in touched))]
        elif added:
            first += [{**dict(r), "hops": 1} for r in s.run(Q1_WORK, work=work_id, kind="ADDED", rels=RELS,
                                                              path=_label(added))]
        for f in first:
            f["sev"] = severity(f["change"], f["rel"], f["whole"])
        strong = [{**f, "keys": [f"{f['work_id']}|{k}" for k in _ancestors(f["path"])]}
                  for f in first if f["rel"] in STRONG]
        second = [{**dict(r), "hops": 2, "whole": False} for r in s.run(Q2, first=strong, cause_work=work_id)] \
            if strong else []
    for f in second:  # 2단계는 1단계보다 무겁지 않다
        f["sev"] = max(severity(f["change"], f["rel"]), f["cap"], key=lambda x: SEVERITY_ORDER[x])
    # 참조가 가리키는 단위(t.path)마다 하나로: 그 아래 여러 조항이 바뀌면 가장 무거운 변경으로 묶는다
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
            " severity, hops, status, resolution_note) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            " ON CONFLICT DO NOTHING RETURNING *",
            (work_id, version_id, from_version, f["cause_path"], f["change"], f["work_id"], cur["id"] if cur else None,
             f["path"], f["rel"], f["evidence"], impact_kind(f["change"], f["rel"], f["whole"]), f["sev"],
             f["hops"], status, note)).fetchone()
        if row:
            out.append(row)
    conn.commit()
    return sorted(out, key=lambda r: (SEVERITY_ORDER[r["severity"]], r["affected_work_id"], r["affected_path"]))
