"""PostgreSQL(기준) → 그래프 행. 규범문서 묶음 단위로 읽어 메모리를 묶음 크기로 제한한다 (spec 2026-10-03 §1).

- Provision 노드 = provision_version 1개. 바뀌지 않은 조항 판본은 여러 판본(dated)에 공유되므로
  valid_from/valid_to(그 판본들의 시행 구간), current, version_ids를 단다.
- 계층 CONTAINS는 판본마다 parent_path로 정하고, 같은 부모-자식이 성립하는 판본 목록(versions)을 단다.
- 참조는 출처 판본의 시행일에 유효했던 대상 조항 판본에 잇는다 (없으면 현행 → 과거 → 조 → missing)."""
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from itertools import pairwise

from reg.graph.model import (
    CONTEXT_UNITS,
    REF_RELS,
    UNIT_LABELS,
    extract_terms,
    full_label,
    is_definition_article,
    uses_terms,
)

WORK_BATCH = 200
TARGET_BATCH = 300


def _iso(d) -> str | None:
    return d.isoformat() if d else None


def family(work_id: str) -> str:
    return "law" if work_id.startswith("kr/law/") else "admrul" if work_id.startswith("kr/admrul/") else "reg"


@dataclass
class Rows:
    institutions: list = field(default_factory=list)
    works: list = field(default_factory=list)
    versions: list = field(default_factory=list)
    next_versions: list = field(default_factory=list)
    provisions: dict = field(default_factory=lambda: defaultdict(list))  # 노드 라벨 → 행
    top: list = field(default_factory=list)
    contains: list = field(default_factory=list)
    amended: list = field(default_factory=list)
    added: list = field(default_factory=list)
    deleted: list = field(default_factory=list)
    terms: list = field(default_factory=list)
    defines: list = field(default_factory=list)
    uses: list = field(default_factory=list)


def fingerprints(conn, work_ids: list[str] | None = None) -> dict[str, str]:
    """규범문서마다 그래프에 영향을 주는 PostgreSQL 상태의 지문. 재적재(rebuild_work)는 provision id를,
    참조 재해석(resolve_and_store)은 reference id를 바꾸므로 max id·건수로 변화를 잡는다."""
    flt = "" if work_ids is None else " WHERE w.id = ANY(%(ids)s)"
    sub = "" if work_ids is None else " WHERE work_id = ANY(%(ids)s)"
    rows = conn.execute(
        "WITH v AS (SELECT work_id, md5(string_agg(id || ':' || version_state || ':' || coalesce(effective_from::text, '')"
        "   || ':' || coalesce(effective_to::text, ''), ',' ORDER BY id)) AS h FROM regulation.work_version" + sub +
        "   GROUP BY work_id),"
        " p AS (SELECT work_id, max(id) AS m, count(*) AS n FROM regulation.provision" + sub + " GROUP BY work_id),"
        " r AS (SELECT work_id, max(id) AS m, count(*) AS n, count(*) FILTER (WHERE review_status = 'REJECTED') AS rj"
        "   FROM regulation.reference" + sub + " GROUP BY work_id)"
        " SELECT w.id, md5(concat_ws('|', w.title, w.kind, w.status, i.code, i.name, array_to_string(i.aliases, ','),"
        "   v.h, p.m, p.n, r.m, r.n, r.rj)) AS fp"
        " FROM regulation.work w LEFT JOIN regulation.institution i ON i.id = w.institution_id"
        " LEFT JOIN v ON v.work_id = w.id LEFT JOIN p ON p.work_id = w.id LEFT JOIN r ON r.work_id = w.id" + flt,
        {"ids": work_ids} if work_ids is not None else None).fetchall()
    return {r["id"]: r["fp"] for r in rows}


def all_work_ids(conn) -> list[str]:
    return [r["id"] for r in conn.execute("SELECT id FROM regulation.work ORDER BY id").fetchall()]


def work_batches(conn, work_ids: list[str], size: int = WORK_BATCH) -> Iterator[Rows]:
    for i in range(0, len(work_ids), size):
        yield work_rows(conn, work_ids[i:i + size])


def work_rows(conn, ids: list[str]) -> Rows:
    out = Rows()
    fps = fingerprints(conn, ids)
    works = conn.execute(
        "SELECT w.id, w.title, w.kind, w.status, i.code, i.name AS inst_name, i.aliases FROM regulation.work w"
        " LEFT JOIN regulation.institution i ON i.id = w.institution_id WHERE w.id = ANY(%s)", (ids,)).fetchall()
    titles = {w["id"]: w["title"] for w in works}
    insts = {}
    for w in works:
        out.works.append({"id": w["id"], "institution": w["code"],
                          "props": {"title": w["title"], "kind": w["kind"], "family": family(w["id"]),
                                    "status": w["status"], "institution": w["code"], "fp": fps.get(w["id"])}})
        if w["code"]:
            insts[w["code"]] = {"code": w["code"], "name": w["inst_name"], "aliases": list(w["aliases"] or [])}
    out.institutions = list(insts.values())
    versions = conn.execute(
        "SELECT id, work_id, effective_from, effective_to, version_state, amendment_kind, promulgated_on"
        " FROM regulation.work_version WHERE work_id = ANY(%s) AND effective_from IS NOT NULL"
        " ORDER BY work_id, effective_from, id", (ids,)).fetchall()
    if not versions:
        return out
    vids = [v["id"] for v in versions]
    by_work: dict[str, list] = defaultdict(list)
    for v in versions:
        by_work[v["work_id"]].append(v)
        out.versions.append({"id": v["id"], "work_id": v["work_id"],
                             "props": {"work_id": v["work_id"], "effective_from": _iso(v["effective_from"]),
                                       "effective_to": _iso(v["effective_to"]), "state": v["version_state"],
                                       "amendment_kind": v["amendment_kind"],
                                       "promulgated_on": _iso(v["promulgated_on"])}})
    for vs in by_work.values():
        out.next_versions += [{"a": a["id"], "b": b["id"]} for a, b in pairwise(vs)]
    members = conn.execute(
        "SELECT work_version_id AS vid, provision_version_id AS pv, ord FROM regulation.version_provision"
        " WHERE work_version_id = ANY(%s) ORDER BY work_version_id, ord", (vids,)).fetchall()
    pvs = {r["id"]: r for r in conn.execute(
        "SELECT DISTINCT pv.id, pv.provision_id, pv.path, pv.parent_path, pv.unit, pv.number_label, pv.heading, pv.text"
        " FROM regulation.version_provision vp JOIN regulation.provision_version pv ON pv.id = vp.provision_version_id"
        " WHERE vp.work_version_id = ANY(%s)", (vids,)).fetchall()}
    by_version: dict[str, list] = defaultdict(list)
    for m in members:
        by_version[m["vid"]].append(m)
    pv_versions: dict[int, list] = defaultdict(list)  # pv → 판본(시행일 순)
    pv_work: dict[int, str] = {}
    contains: dict[tuple, dict] = {}
    pathmaps: dict[str, dict] = {}
    definition_pvs: dict[str, set] = defaultdict(set)  # work → 정의 조와 그 아래 조항 판본
    for v in versions:
        ms = by_version.get(v["id"], [])
        pathmap = {pvs[m["pv"]]["path"]: m["pv"] for m in ms}
        pathmaps[v["id"]] = pathmap
        def_paths = [p for p, i in pathmap.items() if is_definition_article(pvs[i]["unit"], pvs[i]["heading"])]
        for m in ms:
            row = pvs[m["pv"]]
            pv_versions[m["pv"]].append(v)
            pv_work[m["pv"]] = v["work_id"]
            parent = pathmap.get(row["parent_path"]) if row["parent_path"] else None
            if parent is None:
                out.top.append({"vid": v["id"], "pv": m["pv"], "ord": m["ord"]})
            else:
                c = contains.setdefault((parent, m["pv"]), {"a": parent, "b": m["pv"], "ord": m["ord"], "versions": []})
                c["ord"] = m["ord"]
                c["versions"].append(v["id"])
            if any(row["path"] == d or row["path"].startswith(d + ".") for d in def_paths):
                definition_pvs[v["work_id"]].add(m["pv"])
    out.contains = list(contains.values())

    def chain(vid: str, path: str) -> list[tuple[str, str]]:
        out_, seen = [], set()
        pm = pathmaps[vid]
        while path and path in pm and path not in seen:
            seen.add(path)
            r = pvs[pm[path]]
            out_.append((r["unit"], r["number_label"]))
            path = r["parent_path"]
        return out_[::-1]

    for pid, vs in pv_versions.items():
        row, last = pvs[pid], vs[-1]
        open_end = any(v["effective_to"] is None for v in vs)
        out.provisions[UNIT_LABELS.get(row["unit"], "")].append({"pv_id": pid, "props": {
            "work_id": pv_work[pid], "lineage": row["provision_id"], "path": row["path"],
            "parent_path": row["parent_path"], "unit": row["unit"], "label": row["number_label"],
            "heading": row["heading"], "text": row["text"],
            "full_label": full_label(titles.get(pv_work[pid], ""), chain(last["id"], row["path"])),
            "valid_from": _iso(vs[0]["effective_from"]),
            "valid_to": None if open_end else _iso(max(v["effective_to"] for v in vs)),
            "current": any(v["version_state"] == "CURRENT" for v in vs),
            "version_ids": [v["id"] for v in vs]}})
    known = set(pv_versions)
    for c in conn.execute(
            "SELECT kind, from_version_id, to_version_id, from_pv_id, to_pv_id FROM regulation.provision_change"
            " WHERE to_version_id = ANY(%s)", (vids,)).fetchall():
        if c["kind"] == "ADDED" and c["to_pv_id"] in known:
            out.added.append({"pv": c["to_pv_id"], "vid": c["to_version_id"]})
        elif c["kind"] == "DELETED" and c["from_pv_id"] in known:
            out.deleted.append({"pv": c["from_pv_id"], "vid": c["to_version_id"]})
        elif c["kind"] not in ("ADDED", "DELETED") and c["from_pv_id"] in known and c["to_pv_id"] in known:
            out.amended.append({"a": c["from_pv_id"], "b": c["to_pv_id"], "props": {
                "kind": c["kind"], "from_version": c["from_version_id"], "to_version": c["to_version_id"]}})
    # 용어: 정의 조(제목에 '정의') 아래 '"X"이란 …을 말한다'. 같은 이름이 여러 판본에 있으면 가장 늦은 정의를 쓴다
    for wid, dpvs in definition_pvs.items():
        terms: dict[str, dict] = {}
        for pid in sorted(dpvs, key=lambda i: (pv_versions[i][-1]["effective_from"], i)):
            for name, definition in extract_terms(pvs[pid]["text"]):
                t = terms.setdefault(name, {"key": f"{wid}|{name}", "props": {"work_id": wid, "name": name}, "pvs": set()})
                t["props"]["definition"] = definition
                t["pvs"].add(pid)
        names = list(terms)
        for t in terms.values():
            out.terms.append({"key": t["key"], "props": t["props"]})
            out.defines += [{"pv": p, "key": t["key"]} for p in sorted(t["pvs"])]
        for pid, w in pv_work.items():
            if w != wid or pvs[pid]["unit"] in CONTEXT_UNITS:
                continue
            for n in uses_terms(pvs[pid]["text"], names):
                if pid not in terms[n]["pvs"]:
                    out.uses.append({"pv": pid, "key": terms[n]["key"]})
    return out


def _pick(cands: list, d) -> dict | None:
    for c in cands:
        if c["vf"] <= d and (c["vt"] is None or d < c["vt"]):
            return c
    return None


def resolve_target(index: dict, work: str, path: str, d) -> tuple[int | None, str]:
    """(대상 조항 판본 id, 연결 방식). 같은 경로 우선: 출처 시행일 판본 → 현행 → 가장 늦은 과거 판본, 다음은 그 조."""
    art = path.split(".")[0]
    for p, tag in ((path, None), (art, "article")) if art != path else ((path, None),):
        cands = index.get((work, p))
        if not cands:
            continue
        c = _pick(cands, d)
        if c:
            return c["pv"], tag or "as_of"
        c = next((c for c in cands if c["cur"]), None)
        if c:
            return c["pv"], tag or "current"
        return max(cands, key=lambda c: c["vf"])["pv"], tag or "historical"
    return None, "missing"


def reference_batches(conn, work_ids: list[str] | None = None) -> Iterator[list[dict]]:
    """참조 관계 행. work_ids가 있으면 그 규범문서에서 나가거나 그리로 들어오는 참조만.
    행: {rel, kind(prov|work|missing), src, dst, props}."""
    where = ("r.resolution = 'RESOLVED' AND r.review_status <> 'REJECTED' AND r.target_work_id IS NOT NULL"
             " AND r.target_kind IN ('PROVISION', 'WORK', 'ANNEX') AND r.rel_type = ANY(%(rels)s)")
    if work_ids is not None:
        where += " AND (r.work_id = ANY(%(ids)s) OR r.target_work_id = ANY(%(ids)s))"
    args = {"rels": list(REF_RELS), "ids": work_ids}
    targets = [r["t"] for r in conn.execute(
        f"SELECT DISTINCT r.target_work_id AS t FROM regulation.reference r WHERE {where} ORDER BY 1", args).fetchall()]
    for i in range(0, len(targets), TARGET_BATCH):
        chunk = targets[i:i + TARGET_BATCH]
        # 출처 조항 판본이 속한 dated 판본들의 시행일마다 대상을 해석한다
        refs = conn.execute(
            "SELECT r.source_pv_id, r.rel_type, r.target_kind, r.target_work_id, r.target_path, r.evidence_text,"
            " r.resolution, r.review_status, array_agg(DISTINCT v.effective_from) AS dates FROM regulation.reference r"
            " JOIN regulation.version_provision vp ON vp.provision_version_id = r.source_pv_id"
            " JOIN regulation.work_version v ON v.id = vp.work_version_id AND v.effective_from IS NOT NULL"
            f" WHERE {where} AND r.target_work_id = ANY(%(chunk)s) GROUP BY r.id ORDER BY r.id",
            {**args, "chunk": chunk}).fetchall()
        index: dict[tuple, list] = defaultdict(list)
        for r in conn.execute(
                "SELECT v.work_id, pv.path, pv.id AS pv, min(v.effective_from) AS vf,"
                " CASE WHEN bool_or(v.effective_to IS NULL) THEN NULL ELSE max(v.effective_to) END AS vt,"
                " bool_or(v.version_state = 'CURRENT') AS cur"
                " FROM regulation.work_version v JOIN regulation.version_provision vp ON vp.work_version_id = v.id"
                " JOIN regulation.provision_version pv ON pv.id = vp.provision_version_id"
                " WHERE v.work_id = ANY(%s) AND v.effective_from IS NOT NULL GROUP BY v.work_id, pv.path, pv.id",
                (chunk,)).fetchall():
            index[(r["work_id"], r["path"])].append(r)
        rows: dict[tuple, dict] = {}
        for r in refs:
            props = {"evidence": r["evidence_text"] or "", "resolution": r["resolution"],
                     "review_status": r["review_status"], "target_path": r["target_path"]}
            if r["target_kind"] == "WORK" or not r["target_path"]:
                found = {(r["target_work_id"], "work")}
            else:
                found = set()
                for d in r["dates"]:
                    pv, how = resolve_target(index, r["target_work_id"], r["target_path"], d)
                    found.add((pv, how) if pv else (f"{r['target_work_id']}|{r['target_path']}", "missing"))
            for dst, how in found:
                kind = "work" if how == "work" else "missing" if how == "missing" else "prov"
                key = (r["rel_type"], r["source_pv_id"], dst, props["evidence"])
                rows.setdefault(key, {"rel": r["rel_type"], "kind": kind, "src": r["source_pv_id"], "dst": dst,
                                      "work_id": r["target_work_id"], "path": r["target_path"],
                                      "props": {**props, "match": how}})
        yield list(rows.values())
