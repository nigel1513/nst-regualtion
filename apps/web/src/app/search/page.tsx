import Link from "next/link";
import { apiGet, type Institution, type SearchHit, workHref } from "@/lib/api";

export default async function SearchPage({ searchParams }: { searchParams: Promise<{ q?: string; inst?: string }> }) {
  const { q, inst } = await searchParams;
  const insts = await apiGet<Institution[]>("/api/v1/institutions");
  const hits = q && q.trim().length >= 2 ? await apiGet<SearchHit[]>("/api/v1/search", { q: q.trim(), institution: inst }) : null;
  return (
    <main className="mx-auto max-w-4xl px-6 py-6">
      <h1 className="mb-4 text-2xl font-bold">조문 검색</h1>
      <form className="mb-5 flex flex-wrap gap-2">
        <label htmlFor="sq" className="sr-only">검색어</label>
        <input id="sq" name="q" defaultValue={q} placeholder="예: 7일 이내, 숙박비" className="h-10 w-80 rounded-lg border border-[var(--line-strong)] bg-white px-3" />
        <label htmlFor="si" className="sr-only">기관</label>
        <select id="si" name="inst" defaultValue={inst ?? ""} className="h-10 rounded-lg border border-[var(--line-strong)] bg-white px-2 text-sm">
          <option value="">전체 기관</option>
          {insts?.map((i) => <option key={i.code} value={i.code}>{i.name}</option>)}
        </select>
        <button className="btn btn-dark h-10" type="submit">검색</button>
      </form>
      {q && q.trim().length < 2 && <p className="text-sm text-[var(--muted)]">두 글자 이상 입력하세요.</p>}
      {hits && (hits.length === 0 ? <p className="card p-6 text-sm">찾는 조문이 없습니다.</p> : (
        <ul className="flex flex-col gap-2">
          {hits.map((h, i) => {
            const art = h.path.split(".")[0];
            return (
              <li key={i} className="card p-4">
                <Link href={workHref(h.work_id, `?a=${art}#${h.path}`)} className="font-semibold">{h.title} {h.label}{h.heading ? `(${h.heading})` : ""}</Link>
                <span className="ml-2 text-xs text-[var(--muted)]">{h.institution ?? "법령"}</span>
                <p className="mt-1 font-serif text-[15px] leading-relaxed">{h.snippet}</p>
              </li>
            );
          })}
        </ul>
      ))}
    </main>
  );
}
