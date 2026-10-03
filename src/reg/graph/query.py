"""그래프 조회 (spec 2026-10-03 §1.3): 질의응답 근거 확장, 관계도, 조항 이력. Cypher만 쓴다.

기준일(as_of) 유효성: 조항 판본의 시행 구간 valid_from <= as_of < valid_to(열린 끝은 null).
참조는 출처 판본 시행일 기준 대상 판본에 이어져 있으므로, 확장할 때는 같은 계보(lineage)에서 as_of에 유효한 판본으로 옮긴다."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from reg.graph.model import REF_RELS

VALID = "({v}.valid_from <= $as_of AND ({v}.valid_to IS NULL OR {v}.valid_to > $as_of))"
OUT_REASON = {"EXCEPTION": "예외의 원칙 조항", "MUTATIS": "준용 대상", "BASIS": "근거 조항", "DELEGATION": "위임받은 규정",
              "IMPLEMENTS": "시행 근거(상위) 조항", "CITATION": "인용 조항"}
IN_REASON = {"EXCEPTION": "예외 조항", "DELEGATION": "위임 근거 조항"}
PRIORITY = ["용어 정의", "예외 조항", "상위 조문", "준용 대상", "근거 조항", "위임 근거 조항", "위임받은 규정",
            "시행 근거(상위) 조항", "예외의 원칙 조항", "인용 조항"]
FIELDS = ("pv_id", "work_id", "path", "unit", "label", "full_label", "heading", "text", "valid_from", "valid_to")
RELS = "|".join(REF_RELS)

Q_OUT = (f"UNWIND $ids AS id MATCH (s:Provision {{pv_id: id}})-[r:{RELS}]->(t:Provision)"
         f" OPTIONAL MATCH (c:Provision {{lineage: t.lineage}}) WHERE {VALID.format(v='c')}"
         " WITH s, r, t, head(collect(c)) AS c"
         " RETURN s.pv_id AS via, type(r) AS rel, 'out' AS direction, r.evidence AS evidence, coalesce(c, t) AS t,"
         " c IS NULL AS stale")
# 들어오는 예외·위임: 시작 조항과 그 상위 조(같은 계보의 어느 판본이든)를 가리키는 유효한 조항
Q_IN = ("UNWIND $ids AS id MATCH (s:Provision {pv_id: id})"
        f" OPTIONAL MATCH (a:Article)-[:CONTAINS*1..3]->(s) WHERE {VALID.format(v='a')} AND s.path STARTS WITH a.path + '.'"
        " WITH s, [s] + collect(a) AS xs UNWIND xs AS x"
        " MATCH (y:Provision {lineage: x.lineage})<-[r:EXCEPTION|DELEGATION]-(t:Provision)"
        f" WHERE {VALID.format(v='t')} AND t.lineage <> s.lineage"
        " RETURN DISTINCT s.pv_id AS via, type(r) AS rel, 'in' AS direction, r.evidence AS evidence, t,"
        " false AS stale")
Q_PARENT = ("UNWIND $ids AS id MATCH (s:Provision {pv_id: id}) MATCH (a:Article)-[:CONTAINS*1..3]->(s)"
            f" WHERE {VALID.format(v='a')} AND s.path STARTS WITH a.path + '.'"
            " RETURN DISTINCT s.pv_id AS via, a AS t")
# 시작 조항(조면 그 아래 항·호까지)이 쓰는 용어의 정의 조항
Q_TERMS = ("UNWIND $ids AS id MATCH (s:Provision {pv_id: id})"
           f" OPTIONAL MATCH (s)-[:CONTAINS*1..3]->(d:Provision) WHERE {VALID.format(v='d')}"
           " WITH s, [s] + collect(d) AS xs UNWIND xs AS x"
           " MATCH (x)-[:USES]->(term:Term)<-[:DEFINES]-(dp:Provision)"
           f" OPTIONAL MATCH (c:Provision {{lineage: dp.lineage}}) WHERE {VALID.format(v='c')}"
           " WITH s, term, dp, head(collect(c)) AS c"
           " RETURN DISTINCT s.pv_id AS via, term.name AS name, coalesce(c, dp) AS t")


def today() -> date:
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def _as_of(as_of: date | str | None) -> str:
    if as_of is None:
        return today().isoformat()
    return as_of.isoformat() if isinstance(as_of, date) else date.fromisoformat(as_of).isoformat()


def _node(t) -> dict:
    return {k: t.get(k) for k in FIELDS}


def _rank(reason: str) -> int:
    return next((i for i, p in enumerate(PRIORITY) if reason.startswith(p)), len(PRIORITY))


def expand(driver, pv_ids: list[int], as_of: date | str | None = None, depth: int = 1, limit: int = 30) -> list[dict]:
    """근거 조항에서 시작해 예외·준용·근거·위임·시행·인용(1~depth단계), 용어 정의, 상위 조를 덧붙인다.

    항목: 조항 필드 + reason(관계 이유), rel, direction(out|in|term|parent), via(어느 조항에서 왔나), hops, evidence."""
    as_of, depth = _as_of(as_of), max(1, min(int(depth), 3))
    seeds = [int(i) for i in pv_ids]
    found: dict[int, dict] = {}

    def add(t, via, reason, rel, direction, hops, evidence=None, stale=False):
        """stale: 기준일에 유효한 판본이 없는 대상(그 뒤 삭제 등) — 그래프에 이어진 옛 판본을 표시와 함께 준다."""
        item = {**_node(t), "reason": reason + (" (기준일에 없음)" if stale else ""), "rel": rel,
                "direction": direction, "via": via, "hops": hops, "evidence": evidence, "stale": stale}
        cur = found.get(item["pv_id"])
        if item["pv_id"] in seeds or (cur and (cur["hops"], _rank(cur["reason"])) <= (hops, _rank(reason))):
            return False
        found[item["pv_id"]] = item
        return True

    with driver.session() as s:
        for r in s.run(Q_TERMS, ids=seeds, as_of=as_of):
            add(r["t"], r["via"], f"용어 정의: {r['name']}", "DEFINES", "term", 1)
        for r in s.run(Q_PARENT, ids=seeds, as_of=as_of):
            add(r["t"], r["via"], "상위 조문", "CONTAINS", "parent", 1)
        frontier = seeds
        for hop in range(1, depth + 1):
            nxt = []
            for q, reasons in ((Q_OUT, OUT_REASON), (Q_IN, IN_REASON)):
                for r in s.run(q, ids=frontier, as_of=as_of):
                    if add(r["t"], r["via"], reasons[r["rel"]], r["rel"], r["direction"], hop, r["evidence"],
                           r["stale"]) and not r["stale"]:
                        nxt.append(r["t"]["pv_id"])
            frontier = nxt
            if not frontier:
                break
    return sorted(found.values(), key=lambda g: (g["hops"], _rank(g["reason"]), g["work_id"], g["path"]))[:limit]


# ---- 관계도 ----

def _nid(n) -> str:
    labels = set(n.labels)
    p = dict(n)
    if "Provision" in labels:
        return f"pv:{p['pv_id']}"
    for label, prefix, key in (("Version", "ver", "id"), ("Work", "work", "id"), ("Term", "term", "key"),
                               ("MissingProvision", "missing", "key"), ("Institution", "inst", "code")):
        if label in labels:
            return f"{prefix}:{p[key]}"
    return f"node:{n.element_id}"


def _kind(n) -> str:
    labels = sorted(set(n.labels) - {"Provision"})
    return labels[0] if labels else "Provision"


NB_REL = f"{RELS}|AMENDED_TO|ADDED_IN|DELETED_IN|USES|DEFINES"
# 한 조항의 이웃: 참조·계보·용어, 그 판본에서의 부모(판본 또는 상위 조항)와 자식(가장 늦은 판본 기준)
Q_NB = ("MATCH (p:Provision {pv_id: $pv}) CALL (p) {"
        f" MATCH (p)-[r:{NB_REL}]-(x) RETURN r LIMIT $limit"
        " UNION MATCH (x)-[r:CONTAINS]->(p) WHERE NOT x:Version OR x.id = p.version_ids[-1] RETURN r"
        # 참조는 출처 시행일의 대상 판본에 이어져 있다: 같은 계보의 다른 판본을 가리키는 현행 조항도 '이 조를 인용'
        f" UNION MATCH (q:Provision {{lineage: p.lineage}})<-[r:{RELS}]-(x:Provision) WHERE q <> p AND x.current"
        " RETURN r LIMIT $limit"
        " UNION MATCH (p)-[r:CONTAINS]->(x) WHERE $kids AND p.version_ids[-1] IN r.versions RETURN r"
        "} RETURN r, startNode(r) AS a, endNode(r) AS b")
Q_TERM_DEFS = "MATCH (t:Term {key: $key})<-[r:DEFINES]-(d:Provision) RETURN r, d AS a, t AS b"


def neighborhood(driver, pv_id: int, depth: int = 1, limit: int = 200) -> dict | None:
    """관계도: {center, nodes:[{id, kind, labels, props}], edges:[{source, target, type, props}]}.

    depth 2는 참조·계보로 이어진 조항의 이웃(참조·계보·부모)까지 넓힌다. 노드 수는 limit에서 자른다."""
    depth = max(1, min(int(depth), 2))
    nodes: dict[str, dict] = {}
    edges: dict[tuple, dict] = {}

    def take(rec) -> list:
        """rec: (r, a=시작 노드, b=끝 노드). 관계만 받으면 양 끝 노드의 라벨·속성이 비어 있다."""
        r, a, b = rec["r"], rec["a"], rec["b"]
        reached = []
        for n in (a, b):
            nid = _nid(n)
            if nid not in nodes:
                if len(nodes) >= limit:
                    return reached
                nodes[nid] = {"id": nid, "kind": _kind(n), "labels": sorted(n.labels), "props": dict(n)}
            reached.append(n)
        key = (_nid(a), r.type, _nid(b))
        edges.setdefault(key, {"source": key[0], "target": key[2], "type": r.type, "props": dict(r)})
        return reached

    with driver.session() as s:
        center = s.run("MATCH (p:Provision {pv_id: $pv}) RETURN p", pv=int(pv_id)).single()
        if center is None:
            return None
        cid = _nid(center["p"])
        nodes[cid] = {"id": cid, "kind": _kind(center["p"]), "labels": sorted(center["p"].labels),
                      "props": dict(center["p"])}
        frontier, seen = [int(pv_id)], {int(pv_id)}
        for level in range(1, depth + 1):
            nxt = []
            for pv in frontier:
                for rec in list(s.run(Q_NB, pv=pv, limit=limit, kids=level == 1)):
                    r = rec["r"]
                    for n in take(rec):
                        if "Term" in n.labels and level == 1:
                            for d in list(s.run(Q_TERM_DEFS, key=n["key"])):
                                take(d)
                        if ("Provision" in n.labels and r.type in REF_RELS + ("AMENDED_TO",)
                                and n["pv_id"] not in seen):
                            seen.add(n["pv_id"])
                            nxt.append(n["pv_id"])
            frontier = nxt
    return {"center": cid, "nodes": list(nodes.values()), "edges": list(edges.values())}


Q_LINEAGE = ("MATCH (p:Provision {pv_id: $pv}) MATCH (q:Provision {lineage: p.lineage})"
             " OPTIONAL MATCH (prev:Provision)-[a:AMENDED_TO]->(q)"
             " OPTIONAL MATCH (q)-[:ADDED_IN]->(av:Version)"
             " OPTIONAL MATCH (q)-[:DELETED_IN]->(dv:Version)"
             " RETURN q, a.kind AS kind, prev.pv_id AS from_pv, a.from_version AS from_version,"
             " a.to_version AS to_version, av.id AS added, dv.id AS deleted, dv.effective_from AS deleted_on"
             " ORDER BY q.valid_from, q.pv_id")


def lineage(driver, pv_id: int) -> dict | None:
    """조항 이력: 같은 계보의 판본들을 시행일 순으로, 각 판본이 생긴 변경(MODIFIED·RENUMBERED·ANNOTATION_ONLY·ADDED)과 함께."""
    with driver.session() as s:
        rows = list(s.run(Q_LINEAGE, pv=int(pv_id)))
    if not rows:
        return None
    entries, deleted = [], None
    for r in rows:
        q = r["q"]
        entries.append({**_node(q), "version_ids": list(q.get("version_ids") or []),
                        "change": r["kind"] or ("ADDED" if r["added"] else None), "from_pv": r["from_pv"],
                        "from_version": r["from_version"], "to_version": r["to_version"] or r["added"]})
        if r["deleted"]:
            deleted = {"version": r["deleted"], "effective_from": r["deleted_on"]}
    first = rows[0]["q"]
    return {"lineage": first["lineage"], "work_id": first["work_id"], "entries": entries, "deleted_in": deleted}
