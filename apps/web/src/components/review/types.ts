/** 검수 API 계약 (GET /api/v1/review-tasks, src/reg/api/review_routes.py). */
export type Kind = "REFERENCE" | "REF_LAW_AMBIGUOUS" | "REF_LAW_GONE" | "PARSE" | "EFFECTIVE_DATE" | "CONFLICT" | "LOW_TEXT" | "ABOLISHED";
export type Status = "OPEN" | "HOLD" | "RESOLVED" | "DISMISSED";
export type Decision = { action: "resolve" | "dismiss" | "hold" | "reopen"; by: string | null; at: string; note?: string; reason?: string; value?: object } | { auto: string };
export interface ReviewTaskItem {
  id: number; kind: Kind; target: string; work_id: string | null; work_title: string | null; detail: Record<string, unknown>; status: Status;
  created_at: string; kind_label: string; resolved_at: string | null; institution: { code: string; name: string } | null;
  work: { id: string; title: string } | null;
  version: { id: string; effective_from: string | null; state: "CURRENT" | "HISTORICAL" | "FUTURE" | "UNDATED" } | null;
  location: { label: string; path: string | null }; excerpt: { text: string; highlight: [number, number] | null } | null;
  problem: string; todo: string; law_pending: boolean; department: { code: string; name: string | null; scope: "주무부처" } | null;
  assignee: string | null; decision: Decision | null;
  links: { viewer: string | null; source: string | null; pdf: string | null; original: string | null };
}
export interface ReviewTaskList {
  items: ReviewTaskItem[]; total: number; page: number; size: number;
  summary: { open: number; hold: number; unassigned: number; law_pending: number; by_kind: Record<string, number>; by_institution: Record<string, number> } | null;
}

export const KIND_LABEL: Record<Kind, string> = {
  REFERENCE: "참조 미연결", REF_LAW_AMBIGUOUS: "법령명 모호", REF_LAW_GONE: "인용 법령 폐지·삭제", PARSE: "구조 파싱",
  EFFECTIVE_DATE: "시행일 불확실", CONFLICT: "시행일 충돌", LOW_TEXT: "텍스트 부족", ABOLISHED: "폐지 후보",
};
export const REF_KINDS: Kind[] = ["REFERENCE", "REF_LAW_AMBIGUOUS", "REF_LAW_GONE"];

/** 주소 상태: ?status=open|hold|done|all &inst= &kind= &assignee=<이름>|none &q= &law=1 &page= */
export type ReviewQuery = { status: string; inst: string; kind: string; assignee: string; q: string; law: boolean; page: number };

export function parseReviewQuery(sp: Record<string, string | string[] | undefined>): ReviewQuery {
  const one = (k: string) => (typeof sp[k] === "string" ? (sp[k] as string) : "");
  const page = Number.parseInt(one("page"), 10);
  return {
    status: ["open", "hold", "done", "all"].includes(one("status")) ? one("status") : "open",
    inst: one("inst"), kind: one("kind"), assignee: one("assignee").slice(0, 50), q: one("q").slice(0, 100),
    law: one("law") === "1", page: Number.isFinite(page) && page > 0 ? page : 1,
  };
}

export function reviewHref(q: ReviewQuery, change: Partial<ReviewQuery> = {}): string {
  const n = { ...q, page: 1, ...change };
  const p = new URLSearchParams();
  if (n.status !== "open") p.set("status", n.status);
  if (n.inst) p.set("inst", n.inst);
  if (n.kind) p.set("kind", n.kind);
  if (n.assignee) p.set("assignee", n.assignee);
  if (n.q) p.set("q", n.q);
  if (n.law) p.set("law", "1");
  if (n.page > 1) p.set("page", String(n.page));
  const s = p.toString();
  return `/review${s ? `?${s}` : ""}`;
}

/** API 쿼리로: 상태 묶음·법령 적재 대기 묶음을 풀어 쓴다. */
export function apiParams(q: ReviewQuery, size: number): URLSearchParams {
  const p = new URLSearchParams();
  const st = { open: ["OPEN"], hold: ["HOLD"], done: ["RESOLVED", "DISMISSED"], all: ["OPEN", "HOLD", "RESOLVED", "DISMISSED"] }[q.status] ?? ["OPEN"];
  st.forEach((s) => p.append("status", s));
  if (q.inst) p.append("inst", q.inst);
  if (q.kind) p.append("kind", q.kind);
  if (q.assignee) p.set("assignee", q.assignee);
  if (q.q) p.set("q", q.q);
  p.set("group", q.law ? "law_pending" : "default");
  p.set("page", String(q.page));
  p.set("size", String(size));
  return p;
}
