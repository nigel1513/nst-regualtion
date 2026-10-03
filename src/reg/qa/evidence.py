"""근거 확장 (spec 8.2-5): 조 전체 + 예외 조항 + 참조 대상 — 본문은 PostgreSQL에서 읽는다.
M7: 검색이 조 안에서 맞은 항·호(matches)를 matched_paths로 넘겨, 답변이 그 항을 인용하고 화면이 강조하게 한다.
M7-Q: 관계 찾기는 구조 그래프(related, reg.graph.query.expand를 API가 넘김)를 먼저 쓴다 — 용어 정의·예외·위임·준용을
따라간다. 그래프가 없거나 실패하면 예전 PostgreSQL 참조 표 방식으로 돌아간다."""
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field

log = logging.getLogger(__name__)
# 그래프 관계 → 근거 역할 (direction 'parent'는 넣지 않는다: 근거는 이미 조 단위)
GRAPH_ROLE = {"term": "definition", "EXCEPTION": "exception"}
GRAPH_LIMIT = 6


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
    matched_paths: list[str] = field(default_factory=list)
    reason: str | None = None


def sub_label(path: str) -> str:
    """조 아래 경로의 정식 라벨: a27.p1.i3.s가 → '제1항 제3호 가목' (조 자체는 '')."""
    out = []
    for seg in path.split(".")[1:]:
        if m := re.fullmatch(r"p(\d+)(?:~\d+)?", seg):
            out.append(f"제{int(m[1])}항")
        elif m := re.fullmatch(r"i(\d+)(?:-(\d+))?(?:~\d+)?", seg):
            out.append(f"제{int(m[1])}호" + (f"의{int(m[2])}" if m[2] else ""))
        elif m := re.fullmatch(r"s([가-힣])(?:~\d+)?", seg):
            out.append(f"{m[1]}목")
    return " ".join(out)


def _matched(h: dict, art: str) -> list[str]:
    paths = [m["path"] for m in h.get("matches") or []] or [h["path"]]
    return list(dict.fromkeys(p for p in paths if p.startswith(art + ".")))


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


def _version_at(conn, work_id: str, as_of: str | None, release_id: int | str | None = None) -> str | None:
    """참조 대상 규범문서의 버전: 기준일이 없으면 현행, 있으면 그날 시행 중이던 버전 (색인 release 안에서)."""
    rel = (" AND id IN (SELECT work_version_id FROM ops.release_item WHERE release_id = %(rel)s)"
           if release_id is not None else "")
    if as_of is None:
        q = "SELECT id FROM regulation.work_version WHERE work_id = %(w)s AND version_state = 'CURRENT'" + rel
    else:
        q = ("SELECT id FROM regulation.work_version WHERE work_id = %(w)s AND effective_from <= %(d)s" + rel +
             " ORDER BY effective_from DESC, id DESC LIMIT 1")
    r = conn.execute(q, {"w": work_id, "d": as_of, "rel": int(release_id) if release_id is not None else None}).fetchone()
    return r["id"] if r else None


def expand(conn, hits: list[dict], limit_articles: int = 4, budget: int = 8000, as_of: str | None = None,
           release_id: int | str | None = None,
           related: Callable[[list[int], str | None], list[dict]] | None = None) -> list[Evidence]:
    out: list[Evidence] = []
    seen: set[tuple[str, str]] = set()
    used = 0

    def add(version_id: str, article: str, role: str, rel: str | None = None,
            matched: list[str] | None = None, reason: str | None = None,
            part: tuple[str, str, str] | None = None) -> list[int] | None:
        """part=(경로, 라벨, 본문): 조 전체 대신 그 조항 하나만 근거로 (그래프의 용어 정의)."""
        nonlocal used
        if (version_id, article) in seen or (part and (version_id, part[0]) in seen):
            return None
        meta = _version_meta(conn, version_id)
        got = (part[1], part[2], [0]) if part and meta else _article_text(conn, version_id, article) if meta else None
        if part:
            article = part[0]
        if not got or not got[1] or used + len(got[1]) > budget:
            return None
        seen.add((version_id, article))
        used += len(got[1])
        out.append(Evidence(f"E{len(out) + 1}", meta["work_id"], version_id, meta["title"], article, got[0], got[1],
                            role, meta["effective_from"].isoformat() if meta["effective_from"] else None, rel,
                            matched or [], reason))
        return got[2]

    primaries = []
    for h in hits:
        art = h["path"].split("#")[0].split(".")[0]
        if len(primaries) >= limit_articles or (h["version_id"], art) in seen:
            continue
        pv_ids = add(h["version_id"], art, "primary", matched=_matched(h, art))
        if pv_ids:
            primaries.append((h, art, pv_ids))
    if related and primaries and _graph_related(conn, primaries, related, add, as_of, release_id):
        return out
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
            vid = h["version_id"] if c["target_work_id"] == h["work_id"] else _version_at(conn, c["target_work_id"], as_of, release_id)
            if vid and c["art"] != art:
                add(vid, c["art"], "cited", c["rel_type"])
    return out


def _graph_related(conn, primaries, related, add, as_of, release_id) -> bool:
    """그래프가 찾은 관련 조항을 조 단위 근거로 붙인다. 그래프 호출이 실패하면 False (PG 방식으로)."""
    try:
        items = related([i for _, _, ids in primaries for i in ids], as_of)
    except Exception as e:  # 그래프 장애가 답변을 막지 않게 한다
        log.warning("graph expand failed, falling back to PostgreSQL references: %s: %s", type(e).__name__, e)
        return False
    own = {h["work_id"]: h["version_id"] for h, _, _ in reversed(primaries)}
    n = 0
    for it in items:
        # 상위 조문은 이미 조 단위 근거에 들어 있고, 별표·부칙은 길어서 작은 모델이 엉뚱한 숫자를 인용한다 (화면 관계도에서 본다)
        if it.get("direction") == "parent" or not re.match(r"a\d", it["path"]) or n >= GRAPH_LIMIT:
            continue
        art = it["path"].split("#")[0].split(".")[0]
        vid = own.get(it["work_id"]) or _version_at(conn, it["work_id"], as_of, release_id)
        role = GRAPH_ROLE.get(it.get("direction")) or GRAPH_ROLE.get(it.get("rel")) or "cited"
        matched = [it["path"]] if it["path"] != art else []
        part = None
        if role == "definition" and it["path"] != art and it.get("text"):
            label = (it.get("full_label") or "").removeprefix(it.get("title") or "").strip()
            label = re.sub(r"^.*?(?=제\d+조)", "", label) or it["path"]
            part = (it["path"], label, it["text"])
        if vid and add(vid, art, role, it.get("rel"), matched, it.get("reason"), part):
            n += 1
    return True
