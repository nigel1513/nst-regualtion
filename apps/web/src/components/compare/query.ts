/** 기관 비교 주소 상태: ?topic= &inst=a,b (우리 기관 밖 비교 기관) &ours= &view=table|side &item= &diff=1 */
export type CompareQuery = { topic: string; inst: string[]; ours: string; view: "table" | "side"; item: string; diff: boolean };

export function parseCompareQuery(sp: Record<string, string | string[] | undefined>): CompareQuery & { pv: string } {
  const one = (k: string) => (typeof sp[k] === "string" ? (sp[k] as string) : "");
  return {
    topic: one("topic"), inst: one("inst").split(",").map((x) => x.trim().toUpperCase()).filter((x) => /^[A-Z0-9]+$/.test(x)),
    ours: /^[A-Za-z0-9]+$/.test(one("ours")) ? one("ours").toUpperCase() : "", view: one("view") === "side" ? "side" : "table",
    item: one("item"), diff: one("diff") === "1", pv: /^\d+$/.test(one("pv")) ? one("pv") : "",
  };
}

export function compareHref(q: CompareQuery, change: Partial<CompareQuery> = {}): string {
  const n = { ...q, ...change };
  const p = new URLSearchParams();
  if (n.topic) p.set("topic", n.topic);
  if (n.inst.length) p.set("inst", n.inst.join(","));
  if (n.ours) p.set("ours", n.ours);
  if (n.view === "side") p.set("view", "side");
  if (n.item) p.set("item", n.item);
  if (n.diff) p.set("diff", "1");
  const s = p.toString();
  return `/compare${s ? `?${s}` : ""}`;
}
