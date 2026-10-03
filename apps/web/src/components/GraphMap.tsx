"use client";

import { useEffect, useMemo, useState } from "react";
import { workHref } from "@/lib/api";
import { CHANGE_LABEL, REL_LABEL } from "@/lib/format";

// 구조 그래프(Neo4j) 관계도: GET /api/v1/graph/neighborhood · /lineage (M7-G)
type GNode = { id: string; kind: string; labels: string[]; props: Record<string, unknown> };
type GEdge = { source: string; target: string; type: string; props: Record<string, unknown> };
type Hood = { center: string; nodes: GNode[]; edges: GEdge[] };
type Entry = { pv_id: number; full_label: string; valid_from: string | null; valid_to: string | null; change: string | null };
type Lineage = { entries: Entry[]; deleted_in: string | null };

const TYPE_LABEL: Record<string, string> = {
  ...REL_LABEL, CONTAINS: "포함", USES: "용어 사용", DEFINES: "용어 정의", AMENDED_TO: "개정",
};
const COLOR: Record<string, string> = {
  EXCEPTION: "#b7791f", DELEGATION: "#1e4faf", BASIS: "#1e4faf", MUTATIS: "#6b46c1", IMPLEMENTS: "#2f855a",
  CITATION: "#4a5568", USES: "#319795", DEFINES: "#319795", CONTAINS: "#a0aec0",
};
const MAX = 36;
const W = 340, H = 300, CX = W / 2, CY = H / 2;

const str = (v: unknown) => (typeof v === "string" ? v : v == null ? "" : String(v));

function nodeLabel(n: GNode, centerWork: string): string {
  const p = n.props;
  if (n.kind === "Term") return `“${str(p.name)}”`;
  if (n.kind === "MissingProvision") return `${str(p.key)} (대상 없음)`;
  return str(p.work_id) === centerWork ? str(p.label) || str(p.path) : str(p.full_label) || str(p.path);
}

function nodeHref(n: GNode): string | null {
  const p = n.props;
  if (!p.work_id || n.kind === "Term" || n.kind === "MissingProvision") return null;
  return workHref(str(p.work_id), `?a=${encodeURIComponent(str(p.path).split(".")[0])}#${str(p.path)}`);
}

// 조를 바꾸면 부모가 key={pvId}로 새로 그린다 (상태 초기화)
export function GraphMap({ pvId, label }: { pvId: number; label: string }) {
  const [hood, setHood] = useState<Hood | null>(null);
  const [lin, setLin] = useState<Lineage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hide, setHide] = useState(true);

  useEffect(() => {
    let alive = true;
    const get = (u: string) => fetch(u).then((r) => (r.ok ? r.json() : Promise.reject(r.status)));
    get(`/api/v1/graph/neighborhood?pv=${pvId}&depth=2`).then((d) => alive && setHood(d))
      .catch((s) => alive && setError(s === 503 ? "그래프 서버에 연결할 수 없습니다." : "관계도를 불러오지 못했습니다."));
    get(`/api/v1/graph/lineage?pv=${pvId}`).then((d) => alive && setLin(d)).catch(() => {});
    return () => { alive = false; };
  }, [pvId]);

  const view = useMemo(() => {
    if (!hood) return null;
    const byId = new Map(hood.nodes.map((n) => [n.id, n]));
    const center = byId.get(hood.center);
    const lineage = center?.props.lineage;
    const centerWork = str(center?.props.work_id);
    // 같은 조의 다른 판본은 아래 '판본 이력'에서 보여 준다. 구조(포함) 관계만 있는 하위 항·호는 숨길 수 있다.
    const keep = new Set<string>([hood.center]);
    const rel = hood.edges.filter((e) => e.type !== "AMENDED_TO");
    for (const e of rel) {
      for (const id of [e.source, e.target]) {
        const n = byId.get(id);
        if (!n || n.kind === "Version" || (n.props.lineage === lineage && id !== hood.center)) continue;
        if (hide && e.type === "CONTAINS" && !rel.some((x) => x.type !== "CONTAINS" && (x.source === id || x.target === id))) continue;
        keep.add(id);
      }
    }
    const nodes = [...keep].map((id) => byId.get(id)!).filter(Boolean).slice(0, MAX);
    const ids = new Set(nodes.map((n) => n.id));
    const edges = rel.filter((e) => ids.has(e.source) && ids.has(e.target));
    const others = nodes.filter((n) => n.id !== hood.center);
    const pos = new Map<string, [number, number]>([[hood.center, [CX, CY]]]);
    others.forEach((n, i) => {
      const a = (2 * Math.PI * i) / Math.max(others.length, 1) - Math.PI / 2;
      const r = others.length > 12 && i % 2 ? 92 : 125;
      pos.set(n.id, [CX + r * Math.cos(a), CY + r * Math.sin(a)]);
    });
    const types = [...new Set(edges.map((e) => e.type))];
    return { nodes, edges, pos, centerWork, types, truncated: keep.size > MAX };
  }, [hood, hide]);

  return (
    <section className="card p-4" aria-live="polite">
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <h2 className="text-[13px] font-semibold">{label} 관계도</h2>
        <label className="flex items-center gap-1 text-xs text-[var(--muted)]">
          <input type="checkbox" checked={hide} onChange={(e) => setHide(e.target.checked)} /> 하위 항·호 숨기기
        </label>
      </div>
      {error && <p className="text-[13px] text-[var(--muted)]">{error}</p>}
      {!view && !error && <p className="text-[13px] text-[var(--muted)]">불러오는 중…</p>}
      {view && view.nodes.length <= 1 && <p className="text-[13px] text-[var(--muted)]">그래프에 연결된 조항이 없습니다.</p>}
      {view && view.nodes.length > 1 && (
        <>
          <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`${label}과 연결된 조항 관계도`}>
            {view.edges.map((e, i) => {
              const [x1, y1] = view.pos.get(e.source)!, [x2, y2] = view.pos.get(e.target)!;
              return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke={COLOR[e.type] ?? "#a0aec0"}
                strokeWidth={e.type === "CONTAINS" ? 1 : 1.6} strokeDasharray={e.type === "USES" ? "3 3" : undefined}><title>{TYPE_LABEL[e.type] ?? e.type}</title></line>;
            })}
            {view.nodes.map((n) => {
              const [x, y] = view.pos.get(n.id)!;
              const isCenter = n.id === hood!.center;
              const href = nodeHref(n);
              const text = nodeLabel(n, view.centerWork);
              const dot = (
                <g>
                  <circle cx={x} cy={y} r={isCenter ? 9 : 6} fill={isCenter ? "var(--accent)" : n.kind === "Term" ? "#319795" : n.kind === "MissingProvision" ? "#e53e3e" : "#fff"}
                    stroke={n.kind === "Term" ? "#319795" : "var(--accent)"} strokeWidth={1.5} />
                  <text x={x} y={y + (y < CY ? -10 : 17)} textAnchor="middle" fontSize={isCenter ? 11 : 9.5}
                    fontWeight={isCenter ? 600 : 400} fill="currentColor">{text.length > 18 ? text.slice(0, 17) + "…" : text}</text>
                  <title>{`${text}${n.props.heading ? ` (${str(n.props.heading)})` : ""}`}</title>
                </g>
              );
              return href && !isCenter ? <a key={n.id} href={href}>{dot}</a> : <g key={n.id}>{dot}</g>;
            })}
          </svg>
          <ul className="mt-2 flex flex-wrap gap-1.5 text-[11px]">
            {view.types.map((t) => (
              <li key={t} className="flex items-center gap-1"><span className="inline-block h-0.5 w-3" style={{ background: COLOR[t] ?? "#a0aec0" }} />{TYPE_LABEL[t] ?? t}</li>
            ))}
          </ul>
          {view.truncated && <p className="mt-1 text-xs text-[var(--muted)]">연결이 많아 {MAX}개까지만 그렸습니다.</p>}
        </>
      )}
      {lin && lin.entries.length > 1 && (
        <div className="mt-3 border-t border-[var(--line)] pt-2">
          <h3 className="mb-1 text-xs font-semibold">판본 이력</h3>
          <ol className="flex flex-col gap-1 text-xs">
            {lin.entries.map((e) => (
              <li key={e.pv_id} className={`flex justify-between gap-2 ${e.pv_id === pvId ? "font-semibold" : ""}`}>
                <span>{e.valid_from ?? "?"} ~ {e.valid_to ?? "현행"}</span>
                <span className="text-[var(--muted)]">{e.change ? CHANGE_LABEL[e.change] ?? e.change : "제정·최초"}</span>
              </li>
            ))}
          </ol>
          {lin.deleted_in && <p className="mt-1 text-xs text-[var(--muted)]">삭제: {str(lin.deleted_in)}</p>}
        </div>
      )}
    </section>
  );
}
