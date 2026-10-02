import Link from "next/link";
import { apiGet, ApiError, type HSearch, type Institution, type SearchHit, validDate, workHref } from "@/lib/api";
import { fmtDate } from "@/lib/format";

type Result = { kind: "hybrid"; data: HSearch } | { kind: "keyword"; data: SearchHit[]; reason: string };

async function runSearch(q: string, inst?: string, asOf?: string): Promise<Result> {
  try {
    const data = await apiGet<HSearch>("/api/v1/hsearch", { q, institution: inst, as_of: asOf });
    if (data) return { kind: "hybrid", data };
  } catch (e) {
    if (!(e instanceof ApiError) || e.status !== 503) throw e;
  }
  const data = (await apiGet<SearchHit[]>("/api/v1/search", { q, institution: inst })) ?? [];
  return { kind: "keyword", data, reason: "검색 색인 준비 전" };
}

export default async function SearchPage({ searchParams }: { searchParams: Promise<{ q?: string; inst?: string; as_of?: string }> }) {
  const sp = await searchParams;
  const q = typeof sp.q === "string" ? sp.q.trim() : "";
  const inst = typeof sp.inst === "string" && sp.inst ? sp.inst : undefined;
  const asOf = validDate(sp.as_of);
  const insts = await apiGet<Institution[]>("/api/v1/institutions");
  const result = q.length >= 2 ? await runSearch(q, inst, asOf) : null;
  const mode = result?.kind === "hybrid"
    ? (result.data.mode === "hybrid" ? (result.data.reranked ? "하이브리드 검색 · 재정렬" : "하이브리드 검색") : "키워드 검색 (임베딩 서버 응답 없음)")
    : result ? `키워드 검색 (${result.reason})` : null;
  const articleOf = (path: string) => path.split("#")[0].split(".")[0];
  return (
    <main className="mx-auto max-w-4xl px-6 py-6">
      <h1 className="mb-4 text-2xl font-bold">조문 검색</h1>
      <form className="mb-3 flex flex-wrap gap-2">
        <label htmlFor="sq" className="sr-only">검색어</label>
        <input id="sq" name="q" defaultValue={q} placeholder="예: 출장 다녀온 뒤 증빙 제출 기한" className="h-10 w-96 max-w-full rounded-lg border border-[var(--line-strong)] bg-white px-3" />
        <label htmlFor="si" className="sr-only">기관</label>
        <select id="si" name="inst" defaultValue={inst ?? ""} className="h-10 rounded-lg border border-[var(--line-strong)] bg-white px-2 text-sm">
          <option value="">전체 기관</option>
          {insts?.map((i) => <option key={i.code} value={i.code}>{i.name}</option>)}
        </select>
        <label htmlFor="sa" className="sr-only">기준일</label>
        <input id="sa" name="as_of" type="date" defaultValue={asOf} className="h-10 rounded-lg border border-[var(--line-strong)] bg-white px-2 text-sm" />
        <button className="btn btn-dark h-10" type="submit">검색</button>
      </form>
      {q && q.length < 2 && <p className="text-sm text-[var(--muted)]">두 글자 이상 입력하세요.</p>}
      {mode && <p className="mb-4 flex flex-wrap gap-2 text-xs"><span className="chip chip-blue">{mode}</span>{asOf && <span className="chip">{fmtDate(asOf)} 기준</span>}</p>}
      {result?.kind === "hybrid" && (result.data.hits.length === 0 ? <p className="card p-6 text-sm">찾는 조문이 없습니다.</p> : (
        <ul className="flex flex-col gap-2">
          {result.data.hits.map((h) => (
            <li key={h.chunk_id} className="card p-4">
              <Link href={workHref(h.work_id, `?${new URLSearchParams({ a: articleOf(h.path), ...(asOf ? { as_of: asOf } : {}) })}#${encodeURIComponent(h.path.split("#")[0])}`)} className="font-semibold">
                {h.title} {h.path_label}
              </Link>
              <span className="ml-2 text-xs text-[var(--muted)]">{h.institution ?? "법령"}</span>
              <p className="mt-1 line-clamp-3 whitespace-pre-line font-serif text-[15px] leading-relaxed">{h.text.split("\n").slice(1).join("\n").slice(0, 220)}</p>
            </li>
          ))}
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
