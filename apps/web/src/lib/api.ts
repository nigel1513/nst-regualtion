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
  kind: string; provision_id: number; path: string; unit: string;
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

export async function apiGet<T>(path: string, params: Record<string, string | undefined> = {}): Promise<T | null> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) qs.set(k, v);
  const res = await fetch(`${BASE}${path}${qs.size ? `?${qs}` : ""}`, { cache: "no-store" });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  return (await res.json()) as T;
}

export function workHref(id: string, extra = ""): string {
  return "/regulations/" + id.split("/").map(encodeURIComponent).join("/") + extra;
}

export function decodeSegments(segments: string[]): string {
  return segments.map((s) => { try { return decodeURIComponent(s); } catch { return s; } }).join("/");
}
