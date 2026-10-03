/** 규정 찾기 주소 상태 (?q=&inst=&topic=&kind=&status=&sort=&view=&page=). 서버·클라이언트가 함께 쓴다. */
export type RegQuery = { q: string; inst: string[]; instSet: boolean; topic: string[]; kind: string[]; status: string; sort: string; view: string; page: number };

const list = (v: string | string[] | undefined) => (Array.isArray(v) ? v : v ? [v] : []).filter(Boolean);

export function parseRegQuery(sp: Record<string, string | string[] | undefined>): RegQuery {
  const one = (k: string) => (typeof sp[k] === "string" ? (sp[k] as string) : "");
  const page = Number.parseInt(one("page"), 10);
  return {
    q: one("q").trim(), inst: list(sp.inst).filter((i) => i !== "all"), instSet: list(sp.inst).length > 0, topic: list(sp.topic), kind: list(sp.kind),
    status: ["current", "abolished", "all"].includes(one("status")) ? one("status") : "current",
    sort: ["relevance", "title", "recent", "articles", "institution"].includes(one("sort")) ? one("sort") : "",
    view: one("view") === "group" ? "group" : "list", page: Number.isFinite(page) && page > 0 ? page : 1,
  };
}

export function regHref(q: RegQuery, change: Partial<RegQuery> = {}): string {
  const n = { ...q, page: 1, ...change };
  const p = new URLSearchParams();
  if (n.q) p.set("q", n.q);
  // 기관을 비우면 "전체"를 분명히 적는다: 주소에 inst가 없으면 우리 기관이 기본 필터다
  if (n.inst.length === 0) p.append("inst", "all");
  for (const i of n.inst) p.append("inst", i);
  for (const t of n.topic) p.append("topic", t);
  for (const k of n.kind) p.append("kind", k);
  if (n.status !== "current") p.set("status", n.status);
  if (n.sort) p.set("sort", n.sort);
  if (n.view !== "list") p.set("view", n.view);
  if (n.page > 1) p.set("page", String(n.page));
  const s = p.toString();
  return `/regulations${s ? `?${s}` : ""}`;
}
