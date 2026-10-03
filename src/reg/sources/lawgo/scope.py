"""법령 범위 (사용자 결정 2026-10-03): 현행 법령 전체가 아니라 NST·출연연에 필요한 법령만 미러한다.

대상 = (a) 설정 시드(`law.include` + `promote.laws`)
     + (b) 내부규정이 인용한 법령형 이름(`regulation.reference`, 내부 work로 풀린 인용은 뺀다)
     + (c) (a)(b) 각 법령의 시행령·시행규칙(`law.children`).

- `plan_targets`는 순수 함수다(DB·API 없음). 순서는 설정 → 인용 많은 순이고, 자식은 부모 바로 뒤에 둔다.
  `law.max_targets`로 자르고 잘린 것은 `dropped`로 보고한다.
- 이름은 `norm_title`(띄어쓰기·가운뎃점 무시)로 묶는다. 같은 법령의 여러 표기는 인용 수를 더한다.
- `select_rows`는 law.go.kr 목록 행을 계획에 맞춘다: 정식명 또는 약칭 → 맞은 법령의 정식명 + 시행령·시행규칙.
  이미 미러에 있는 법령(`keep_ids`)은 이름이 바뀌어도 계속 따라간다.
"""
from collections import Counter
from dataclasses import dataclass, field

from reg.core.ingest.loader import norm_title
from reg.sources.lawgo.config import LawgoConfig

CONFIG, CITED, CHILD, KEPT = "config", "cited", "child", "mirrored"


def is_law_name(name: str | None, suffixes: list[str], exclude: list[str], exclude_suffixes: list[str] = ()) -> bool:
    n = norm_title(name or "")
    if not n or n in {norm_title(x) for x in exclude} or any(n.endswith(norm_title(s)) for s in exclude_suffixes):
        return False
    return any(n.endswith(norm_title(s)) for s in suffixes)


@dataclass
class Target:
    norm: str
    name: str
    reasons: list[str] = field(default_factory=list)
    citations: int = 0
    parent: str | None = None  # 자식이면 부모의 정규화 이름

    def add(self, reason: str) -> None:
        if reason not in self.reasons:
            self.reasons.append(reason)


@dataclass
class TargetPlan:
    targets: list[Target]
    dropped: list[Target]
    max_targets: int
    children: list[str]

    def by_norm(self) -> dict[str, Target]:
        return {t.norm: t for t in self.targets}

    def counts(self) -> dict[str, int]:
        c = {r: sum(1 for t in self.targets if r in t.reasons) for r in (CONFIG, CITED, CHILD)}
        return c | {"total": len(self.targets), "dropped": len(self.dropped)}


def _is_child(norm: str, children: list[str]) -> bool:
    return any(norm.endswith(norm_title(c)) for c in children)


def plan_targets(seeds: list[str], cited: dict[str, int], *, suffixes: list[str], exclude: list[str],
                 children: list[str], max_targets: int, min_citations: int = 1,
                 exclude_suffixes: list[str] = ()) -> TargetPlan:
    """seeds: 설정 이름(순서 유지). cited: {인용된 이름 원문: 인용 수} (법령형이 아닌 이름은 여기서 거른다)."""
    counts: dict[str, int] = Counter()
    spellings: dict[str, Counter] = {}
    for name, n in cited.items():
        if not is_law_name(name, suffixes, exclude, exclude_suffixes):
            continue
        k = norm_title(name)
        counts[k] += n
        spellings.setdefault(k, Counter())[name.strip()] += n
    entries: dict[str, Target] = {}
    order: list[str] = []

    def put(norm: str, name: str, reason: str, parent: str | None = None) -> None:
        t = entries.get(norm)
        if t is None:
            t = entries[norm] = Target(norm, name, citations=counts.get(norm, 0), parent=parent)
            order.append(norm)
        t.add(reason)
        if parent and t.parent is None:
            t.parent = parent

    bases: list[tuple[str, str, str]] = []
    for s in seeds:
        if s and s.strip():
            bases.append((norm_title(s), s.strip(), CONFIG))
    ranked = sorted((k for k, n in counts.items() if n >= min_citations), key=lambda k: (-counts[k], k))
    bases += [(k, spellings[k].most_common(1)[0][0], CITED) for k in ranked]
    for norm, name, reason in bases:
        put(norm, name, reason)
        if _is_child(norm, children):
            continue
        for c in children:
            put(norm + norm_title(c), f"{entries[norm].name} {c}", CHILD, parent=norm)
    all_t = [entries[k] for k in order]
    return TargetPlan(all_t[:max_targets], all_t[max_targets:], max_targets, list(children))


@dataclass
class Selection:
    rows: list
    reasons: dict[str, list[str]]  # mst → 사유
    unmatched: list[str]           # 목록에서 찾지 못한 대상 이름
    current: int                   # 목록의 현행 행 수
    plan: TargetPlan

    def stats(self, sample: int = 0) -> dict:
        by = Counter(r for rs in self.reasons.values() for r in rs)
        out = {"targets": len(self.plan.targets), "dropped_by_cap": len(self.plan.dropped),
               "selected": len(self.rows), "skipped": self.current - len(self.rows),
               "unmatched_targets": len(self.unmatched), "by_reason": dict(sorted(by.items()))}
        if sample:
            out["unmatched_sample"] = self.unmatched[:sample]
        return out


def select_rows(plan: TargetPlan, rows: list, keep_ids: set[str] | frozenset = frozenset()) -> Selection:
    """rows: LawRow 목록(현행이 아닌 행은 건너뛴다)."""
    want = plan.by_norm()
    cur = [r for r in rows if r.status == "현행"]
    picked: dict[str, tuple] = {}
    hit: set[str] = set()
    official_children: dict[str, str] = {}  # 정식명 자식 norm → 계획의 자식 norm
    for r in cur:
        t = want.get(norm_title(r.name)) or (want.get(norm_title(r.abbr)) if r.abbr else None)
        if t is None:
            continue
        picked[r.mst] = (r, list(t.reasons))
        hit.add(t.norm)
        if not _is_child(t.norm, plan.children):
            for c in plan.children:
                official_children.setdefault(norm_title(r.name) + norm_title(c), t.norm + norm_title(c))
    for r in cur:
        k = norm_title(r.name)
        if r.mst not in picked and k in official_children:
            picked[r.mst] = (r, [CHILD])
            hit.add(official_children[k])
    for r in cur:
        if r.mst not in picked and r.law_id in keep_ids:
            picked[r.mst] = (r, [KEPT])
    sel = [picked[r.mst][0] for r in cur if r.mst in picked]
    unmatched = [t.name for t in plan.targets if t.norm not in hit]
    return Selection(sel, {m: rs for m, (_, rs) in picked.items()}, unmatched, len(cur), plan)


def cited_law_counts(conn) -> dict[str, int]:
    """내부규정 인용 이름별 인용 수(원문 그대로). 같은 기관 내부 work로 풀린 인용은 뺀다. 읽기만 한다."""
    rows = conn.execute("SELECT target_name AS n, count(*)::int AS c FROM regulation.reference"
                        " WHERE target_name IS NOT NULL AND (target_work_id IS NULL OR target_work_id NOT LIKE 'kr/reg/%')"
                        " GROUP BY 1").fetchall()
    return {r["n"]: r["c"] for r in rows if r["n"]}


def law_plan(conn, cfg: LawgoConfig) -> TargetPlan:
    seeds = list(dict.fromkeys(cfg.law_include + cfg.promote_laws))
    return plan_targets(seeds, cited_law_counts(conn), suffixes=cfg.law_cited_suffixes, exclude=cfg.law_cited_exclude,
                        children=cfg.law_children, max_targets=cfg.law_max_targets,
                        min_citations=cfg.law_min_citations, exclude_suffixes=cfg.law_cited_exclude_suffixes)


def mirrored_law_ids(conn) -> set[str]:
    return {r["law_id"] for r in conn.execute(
        "SELECT law_id FROM law.law_master WHERE family = 'law' AND status = '현행'").fetchall()}
