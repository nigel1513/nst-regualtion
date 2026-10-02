const BASE = process.env.REG_API_URL ?? "http://127.0.0.1:21061";

export type VersionSummary = {
  id: string; effective_from: string | null; version_state: string; effective_status: string;
  validation_status: string; amendment_no: string | null;
};
export type Work = { id: string; title: string; kind: string; institution: string | null; version?: VersionSummary | null };
export type Institution = { code: string; name: string; kind: string; works: number };
export type VersionRow = VersionSummary & {
  effective_to: string | null; effective_basis: string; amendment_kind: string | null; promulgated_on: string | null;
};
export type VersionMeta = VersionRow & {
  work_id: string; title: string; posted_on: string | null; class_code: string | null;
  source: { source: string; url: string; mime: string; view_status: string; file_name: string | null; has_view: boolean };
};
export type Anchor = { page: number; bbox: [number, number, number, number] | null } | null;
export type Provision = {
  id: number; provision_id: number; path: string; unit: string; label: string; heading: string | null; text: string;
  parent: string | null; annotations: string[]; deleted: boolean; anchor: Anchor; effective_override: string | null;
};
export type Ref = {
  start: number; end: number; rel_type: string; target_kind: string; target_work_id: string | null;
  target_path: string | null; target_name: string | null; resolution: string;
};
export type ViewData = {
  work: Work; version: VersionMeta; provisions: Provision[]; refs: Record<string, Ref[]>;
  history: { kind: string; date: string; number: string | null }[]; tasks: { kind: string; detail: Record<string, unknown> }[];
};
export type Change = {
  kind: string; moved: boolean; provision_id: number; path: string; unit: string;
  from: { label: string; heading: string | null; text: string; annotations: string[] } | null;
  to: { label: string; heading: string | null; text: string; annotations: string[] } | null;
};
export type DiffData = { from: VersionRow; to: VersionRow; changes: Change[] };
export type SearchHit = {
  work_id: string; title: string; institution: string | null; version_id: string; path: string; label: string;
  heading: string | null; snippet: string;
};
export type ReviewTask = {
  id: number; kind: string; target: string; work_id: string | null; work_title: string | null;
  detail: Record<string, unknown>; status: string; created_at: string;
};

export type HHit = {
  chunk_id: string; work_id: string; version_id: string; path: string; path_label: string; title: string;
  institution: string | null; text: string; score: number; rerank_score?: number;
};
export type HSearch = { mode: "hybrid" | "bm25"; reranked: boolean; release_id: string | null; hits: HHit[] };

export type QaEvidence = {
  id: string; work_id: string; version_id: string; title: string; path: string; label: string; text: string;
  role: string; effective_from: string | null; rel: string | null;
};
export type QaAnswer = { 결론: string; 근거: { id: string; 인용: string }[]; 설명: string; 확인_필요: string[]; 문의처: string };
export type QaResult = {
  id: number; status: "answered" | "need_institution" | "not_found" | "evidence_only"; institution: string | null;
  as_of: string | null; question_type: string | null; evidence: QaEvidence[]; answer: QaAnswer | null;
  verification: { ok: boolean; citations_exist?: boolean; quotes_match?: boolean; numbers_match?: boolean; consistent?: boolean; problems: string[] } | null;
  verdict_source: string | null; release_id: string | null; note: string | null; options?: { code: string; name: string }[];
};

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export async function apiGet<T>(path: string, params: Record<string, string | undefined> = {}): Promise<T | null> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) qs.set(k, v);
  const res = await fetch(`${BASE}${path}${qs.size ? `?${qs}` : ""}`, { cache: "no-store" });
  if (res.status === 404) return null;
  if (!res.ok) throw new ApiError(res.status, `API ${res.status}: ${await res.text()}`);
  return (await res.json()) as T;
}

/** 기준일 쿼리 값 검증: YYYY-MM-DD 한 개만 받는다 (잘못된 값으로 API 500이 나지 않게). */
export function validDate(v: string | string[] | undefined): string | undefined {
  return typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v) && !Number.isNaN(Date.parse(v)) ? v : undefined;
}

export function workHref(id: string, extra = ""): string {
  return "/regulations/" + id.split("/").map(encodeURIComponent).join("/") + extra;
}

export function sourceHref(id: string, extra = ""): string {
  return "/source/" + id.split("/").map(encodeURIComponent).join("/") + extra;
}

export function decodeSegments(segments: string[]): string {
  return segments.map((s) => { try { return decodeURIComponent(s); } catch { return s; } }).join("/");
}

export type Alert = {
  id: number; severity: "HIGH" | "MEDIUM" | "LOW"; impact_kind: string; status: string; hops: number;
  cause_work_id: string; cause_version_id: string; cause_path: string; cause_change: string; cause_title: string | null;
  affected_work_id: string; affected_version_id: string | null; affected_path: string; affected_title: string | null;
  rel_type: string; evidence: string | null; resolution_note: string | null; created_at: string; institution: string | null;
};
export type AlertDetail = Alert & { cause_old: string | null; cause_new: string | null; affected_text: string | null; recipients: string[] };

/** M6-2: 규범문서 폐지 상태 (works·work/view 응답의 work에 붙는다) */
export type WorkStatusFields = { status?: "ACTIVE" | "ABOLISHED_CANDIDATE" | "ABOLISHED"; abolished_on?: string | null };
