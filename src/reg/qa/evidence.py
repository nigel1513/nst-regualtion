"""근거 확장 (spec 8.2-5): 조 전체 + 예외 조항 + 참조 대상 — PostgreSQL에서 읽는다."""
from dataclasses import dataclass


@dataclass
class Evidence:
    id: str
    work_id: str
    version_id: str
    title: str
    path: str
    label: str
    text: str
    role: str
    effective_from: str | None
    rel: str | None = None


def _article_text(conn, version_id: str, article: str) -> tuple[str, str, list[int]] | None:
    rows = conn.execute(
        "SELECT pv.id, pv.path, pv.unit, pv.number_label, pv.heading, pv.text FROM regulation.version_provision vp"
        " JOIN regulation.provision_version pv ON pv.id = vp.provision_version_id"
        " WHERE vp.work_version_id = %s AND (pv.path = %s OR pv.path LIKE %s) ORDER BY vp.ord",
        (version_id, article, article + ".%")).fetchall()
    if not rows:
        return None
    head = rows[0]
    label = head["number_label"] + (f"({head['heading']})" if head["heading"] else "")
    lines = [head["text"]] + [(f"{r['number_label']} " if r["unit"] in ("paragraph", "item", "subitem") else "") + r["text"]
                              for r in rows[1:]]
    return label, "\n".join(x for x in lines if x), [r["id"] for r in rows]


def _version_meta(conn, version_id: str) -> dict | None:
    return conn.execute("SELECT id, work_id, title, effective_from FROM regulation.work_version WHERE id = %s",
                        (version_id,)).fetchone()


def _current_version(conn, work_id: str) -> str | None:
    r = conn.execute("SELECT id FROM regulation.work_version WHERE work_id = %s AND version_state = 'CURRENT'",
                     (work_id,)).fetchone()
    return r["id"] if r else None


def expand(conn, hits: list[dict], limit_articles: int = 4, budget: int = 8000) -> list[Evidence]:
    out: list[Evidence] = []
    seen: set[tuple[str, str]] = set()
    used = 0

    def add(version_id: str, article: str, role: str, rel: str | None = None) -> list[int] | None:
        nonlocal used
        if (version_id, article) in seen:
            return None
        meta = _version_meta(conn, version_id)
        got = _article_text(conn, version_id, article) if meta else None
        if not got or used + len(got[1]) > budget:
            return None
        seen.add((version_id, article))
        used += len(got[1])
        out.append(Evidence(f"E{len(out) + 1}", meta["work_id"], version_id, meta["title"], article, got[0], got[1],
                            role, meta["effective_from"].isoformat() if meta["effective_from"] else None, rel))
        return got[2]

    primaries = []
    for h in hits:
        art = h["path"].split("#")[0].split(".")[0]
        if len(primaries) >= limit_articles or (h["version_id"], art) in seen:
            continue
        pv_ids = add(h["version_id"], art, "primary")
        if pv_ids:
            primaries.append((h, art, pv_ids))
    for h, art, pv_ids in primaries:
        exc = conn.execute(
            "SELECT DISTINCT split_part(spv.path, '.', 1) AS art FROM regulation.reference r"
            " JOIN regulation.provision_version spv ON spv.id = r.source_pv_id"
            " JOIN regulation.version_provision vp ON vp.provision_version_id = spv.id AND vp.work_version_id = %s"
            " WHERE r.rel_type = 'EXCEPTION' AND r.target_work_id = %s AND (r.target_path = %s OR r.target_path LIKE %s)"
            " LIMIT 3", (h["version_id"], h["work_id"], art, art + ".%")).fetchall()
        for e in exc:
            if e["art"] != art:
                add(h["version_id"], e["art"], "exception", "EXCEPTION")
        cites = conn.execute(
            "SELECT DISTINCT r.target_work_id, split_part(r.target_path, '.', 1) AS art, r.rel_type"
            " FROM regulation.reference r WHERE r.source_pv_id = ANY(%s) AND r.resolution = 'RESOLVED'"
            " AND r.target_kind = 'PROVISION' LIMIT 3", (pv_ids,)).fetchall()
        for c in cites:
            vid = h["version_id"] if c["target_work_id"] == h["work_id"] else _current_version(conn, c["target_work_id"])
            if vid and c["art"] != art:
                add(vid, c["art"], "cited", c["rel_type"])
    return out
