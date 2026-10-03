import Link from "next/link";
import { Highlight } from "@/components/Highlight";
import {
  apiGet, ApiError, type Facet, type HHit, type HSearch, type HUnit, type Institution, type LookupHit, type SearchHit,
  validDate, workHref,
} from "@/lib/api";
import { fmtDate } from "@/lib/format";

type Result = { kind: "hybrid"; data: HSearch } | { kind: "keyword"; data: SearchHit[]; reason: string };
type Params = { q?: string; inst?: string; kind?: string; as_of?: string };

const KINDS: Record<string, string> = { reg: "내부규정", law: "법령·행정규칙", admrul: "행정규칙" };
const DEPTH: Record<string, number> = { paragraph: 0, item: 1, subitem: 2 };

async function runSearch(q: string, inst?: string, kind?: string, asOf?: string): Promise<Result> {
  try {
    const data = await apiGet<HSearch>("/api/v1/hsearch", { q, institution: inst, kind, as_of: asOf });
    if (data) return { kind: "hybrid", data };
  } catch (e) {
    if (!(e instanceof ApiError) || e.status !== 503) throw e;
  }
  const data = (await apiGet<SearchHit[]>("/api/v1/search", { q, institution: inst })) ?? [];
  return { kind: "keyword", data, reason: "검색 색인 준비 전" };
}

function provisionHref(workId: string, path: string, asOf?: string) {
  const article = path.split(".")[0];
  return workHref(workId, `?${new URLSearchParams({ a: article, ...(asOf ? { as_of: asOf } : {}) })}#${encodeURIComponent(path)}`);
}

function searchHref(p: Params, change: Partial<Params>) {
  const next = { ...p, ...change };
  const qs = new URLSearchParams(Object.entries(next).filter(([, v]) => v) as [string, string][]);
  return `/search?${qs}`;
}

/** 같은 경로의 창(#n) 조각은 한 줄로 붙인다. */
function mergeWindows(units: HUnit[]): HUnit[] {
  const out: HUnit[] = [];
  for (const u of units) {
    const last = out[out.length - 1];
    if (last && last.path === u.path) last.text += u.text;
    else out.push({ ...u });
  }
  return out;
}

/** 조 카드에 보일 단위: 짧은 조는 전부, 긴 조는 맞은 단위와 그 상위(항)만. */
function visibleUnits(units: HUnit[], matched: Set<string>, articlePath?: string): { shown: HUnit[]; hidden: number } {
  const body = units.filter((u) => u.unit in DEPTH || u.unit === "supp_article" || (u.path === articlePath && u.text));
  if (body.length <= 8 || matched.size === 0) return { shown: body, hidden: 0 };
  const keep = new Set<string>();
  for (const p of matched) {
    keep.add(p);
    let cur = units.find((u) => u.path === p)?.parent_path;
    while (cur) { keep.add(cur); cur = units.find((u) => u.path === cur)?.parent_path; }
  }
  const shown = body.filter((u) => keep.has(u.path));
  return { shown, hidden: body.length - shown.length };
}

function UnitLine({ u, hl, shaded }: { u: HUnit; hl?: string | null; shaded: boolean }) {
  const depth = DEPTH[u.unit] ?? 0;
  return (
    <p className={`rounded-md py-0.5 pr-2 font-serif text-[15px] leading-relaxed ${u.unit in DEPTH ? "" : "line-clamp-6 whitespace-pre-line"} ${shaded ? "border-l-[3px] border-[var(--accent)] bg-[var(--accent-soft)]" : "border-l-[3px] border-transparent"}`}
      style={{ paddingLeft: `${8 + depth * 18}px` }}>
      {u.marker && u.unit in DEPTH && <span className="mr-1 text-[var(--ink-2)]">{u.marker}</span>}
      {hl ? <Highlight text={hl} /> : u.text}
    </p>
  );
}

function ArticleCard({ h, asOf }: { h: HHit; asOf?: string }) {
  const matches = h.matches ?? [];
  const byPath = new Map(matches.map((m) => [m.path, m]));
  const matched = new Set(matches.filter((m) => m.path !== h.article_path).map((m) => m.path));
  const units = mergeWindows(h.units ?? []);
  const { shown, hidden } = visibleUnits(units, matched, h.article_path);
  const labels = matches.filter((m) => m.path !== h.article_path && m.label).map((m) => m.label as string);
  return (
    <li className="card p-4">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <Link href={provisionHref(h.work_id, h.path, asOf)} className="font-semibold">{h.title} {h.path_label}</Link>
        <span className="text-xs text-[var(--muted)]">{h.institution_name ?? h.institution ?? "법령"}</span>
        {labels.map((l) => <span key={l} className="chip chip-blue">{l}</span>)}
      </div>
      {units.length > 0 ? (
        <div className="mt-2 flex flex-col gap-0.5">
          {shown.map((u) => <UnitLine key={u.path} u={u} hl={byPath.get(u.path)?.highlight} shaded={matched.has(u.path)} />)}
          {hidden > 0 && (
            <details className="mt-1 text-sm">
              <summary className="cursor-pointer text-[var(--muted)]">조 전체 보기 ({hidden}줄 더)</summary>
              <div className="mt-1 flex flex-col gap-0.5">
                {units.filter((u) => u.unit in DEPTH).map((u) => <UnitLine key={u.path} u={u} hl={byPath.get(u.path)?.highlight} shaded={matched.has(u.path)} />)}
              </div>
            </details>
          )}
        </div>
      ) : (
        <p className="mt-1 line-clamp-3 whitespace-pre-line font-serif text-[15px] leading-relaxed">{h.text.split("\n").slice(1).join("\n").slice(0, 220)}</p>
      )}
    </li>
  );
}

function LookupBox({ hits, asOf }: { hits: LookupHit[]; asOf?: string }) {
  return (
    <section aria-label="조문 바로가기" className="card mb-4 border-[var(--accent-line)] p-4">
      <p className="mb-2 text-xs font-semibold text-[var(--accent)]">조문 바로가기</p>
      <ul className="flex flex-col gap-2">
        {hits.map((x) => (
          <li key={x.doc_id}>
            <Link href={provisionHref(x.work_id, x.path, asOf)} className="font-semibold">{x.full_label}</Link>
            <span className="ml-2 text-xs text-[var(--muted)]">{x.institution_name ?? x.institution ?? "법령"}</span>
            <p className="mt-0.5 line-clamp-4 whitespace-pre-line font-serif text-[15px] leading-relaxed">
              {x.unit === "article" ? (x.article_text ?? x.text).split("\n").slice(1).join("\n") : `${x.marker && x.unit !== "annex" ? x.marker + " " : ""}${x.text}`}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}

function FacetRow({ label, items, active, href }: { label: string; items: Facet[]; active?: string; href: (v?: string) => string }) {
  if (items.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-xs">
      <span className="mr-1 text-[var(--muted)]">{label}</span>
      {active && <Link href={href(undefined)} className="chip">전체</Link>}
      {items.map((f) => (
        <Link key={f.value} href={href(f.value)} aria-current={active === f.value ? "true" : undefined}
          className={`chip ${active === f.value ? "chip-blue" : ""}`}>
          {f.name ?? KINDS[f.value] ?? f.value} <span className="ml-1 text-[var(--muted)]">{f.count}</span>
        </Link>
      ))}
    </div>
  );
}

export default async function SearchPage({ searchParams }: { searchParams: Promise<Params> }) {
  const sp = await searchParams;
  const q = typeof sp.q === "string" ? sp.q.trim() : "";
  const inst = typeof sp.inst === "string" && sp.inst ? sp.inst : undefined;
  const kind = typeof sp.kind === "string" && sp.kind in KINDS ? sp.kind : undefined;
  const asOf = validDate(sp.as_of);
  const params: Params = { q, inst, kind, as_of: asOf };
  const insts = await apiGet<Institution[]>("/api/v1/institutions");
  const result = q.length >= 2 ? await runSearch(q, inst, kind, asOf) : null;
  const mode = result?.kind === "hybrid"
    ? (result.data.mode === "hybrid" ? (result.data.reranked ? "하이브리드 검색 · 재정렬" : "하이브리드 검색") : "키워드 검색 (임베딩 서버 응답 없음)")
    : result ? `키워드 검색 (${result.reason})` : null;
  const facets = result?.kind === "hybrid" ? result.data.facets : undefined;
  return (
    <main className="mx-auto max-w-4xl px-6 py-6">
      <h1 className="mb-4 text-2xl font-bold">조문 검색</h1>
      <form className="mb-3 flex flex-wrap gap-2">
        <label htmlFor="sq" className="sr-only">검색어</label>
        <input id="sq" name="q" defaultValue={q} placeholder="예: 출장 증빙 제출 기한 · 천문연 여비규정 27조 1항" className="h-10 w-96 max-w-full rounded-lg border border-[var(--line-strong)] bg-white px-3" />
        <label htmlFor="si" className="sr-only">기관</label>
        <select id="si" name="inst" defaultValue={inst ?? ""} className="h-10 rounded-lg border border-[var(--line-strong)] bg-white px-2 text-sm">
          <option value="">전체 기관</option>
          {insts?.map((i) => <option key={i.code} value={i.code}>{i.name}</option>)}
        </select>
        <label htmlFor="sk" className="sr-only">종류</label>
        <select id="sk" name="kind" defaultValue={kind ?? ""} className="h-10 rounded-lg border border-[var(--line-strong)] bg-white px-2 text-sm">
          <option value="">전체 종류</option>
          {Object.entries(KINDS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <label htmlFor="sa" className="sr-only">기준일</label>
        <input id="sa" name="as_of" type="date" defaultValue={asOf} className="h-10 rounded-lg border border-[var(--line-strong)] bg-white px-2 text-sm" />
        <button className="btn btn-dark h-10" type="submit">검색</button>
      </form>
      {q && q.length < 2 && <p className="text-sm text-[var(--muted)]">두 글자 이상 입력하세요.</p>}
      {mode && <p className="mb-3 flex flex-wrap gap-2 text-xs"><span className="chip chip-blue">{mode}</span>{asOf && <span className="chip">{fmtDate(asOf)} 기준</span>}</p>}
      {facets && (
        <div className="mb-4 flex flex-col gap-2">
          <FacetRow label="기관" items={facets.institution} active={inst} href={(v) => searchHref(params, { inst: v })} />
          <FacetRow label="종류" items={facets.kind} active={kind} href={(v) => searchHref(params, { kind: v })} />
        </div>
      )}
      {result?.kind === "hybrid" && (result.data.lookup?.length ?? 0) > 0 && <LookupBox hits={result.data.lookup ?? []} asOf={asOf} />}
      {result?.kind === "hybrid" && (result.data.hits.length === 0 ? <p className="card p-6 text-sm">찾는 조문이 없습니다.</p> : (
        <ul className="flex flex-col gap-2">
          {result.data.hits.map((h) => <ArticleCard key={h.chunk_id} h={h} asOf={asOf} />)}
        </ul>
      ))}
      {result?.kind === "keyword" && (result.data.length === 0 ? <p className="card p-6 text-sm">찾는 조문이 없습니다.</p> : (
        <ul className="flex flex-col gap-2">
          {result.data.map((h, i) => (
            <li key={i} className="card p-4">
              <Link href={workHref(h.work_id, `?a=${encodeURIComponent(h.path.split(".")[0])}#${encodeURIComponent(h.path)}`)} className="font-semibold">{h.title} {h.label}{h.heading ? `(${h.heading})` : ""}</Link>
              <span className="ml-2 text-xs text-[var(--muted)]">{h.institution ?? "법령"}</span>
              <p className="mt-1 font-serif text-[15px] leading-relaxed">{h.snippet}</p>
            </li>
          ))}
        </ul>
      ))}
    </main>
  );
}
