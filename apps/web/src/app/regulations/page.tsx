import Link from "next/link";
import { AbolishBadge } from "@/components/AbolishBadge";
import { apiGet, type Institution, type Work, type WorkStatusFields, workHref } from "@/lib/api";
import { fmtDate, STATE_LABEL } from "@/lib/format";

export default async function RegulationsPage({ searchParams }: { searchParams: Promise<{ inst?: string; q?: string; kind?: string }> }) {
  const { inst, q, kind } = await searchParams;
  const [insts, works] = await Promise.all([
    apiGet<Institution[]>("/api/v1/institutions"),
    apiGet<(Work & WorkStatusFields)[]>("/api/v1/works", { institution: inst, q, kind }),
  ]);
  const chip = (href: string, label: string, on: boolean) => (
    <Link key={href} href={href} className={`chip ${on ? "chip-blue" : ""}`}>{label}</Link>
  );
  return (
    <main className="mx-auto max-w-6xl px-6 py-6">
      <h1 className="mb-4 text-2xl font-bold">규정·법령</h1>
      <form className="mb-4 flex flex-wrap items-center gap-2" action="/regulations">
        {inst && <input type="hidden" name="inst" value={inst} />}
        <label htmlFor="q" className="sr-only">규정명</label>
        <input id="q" name="q" defaultValue={q} placeholder="규정명으로 찾기" className="h-9 w-72 rounded-lg border border-[var(--line-strong)] bg-white px-3 text-sm" />
        <button className="btn btn-dark" type="submit">찾기</button>
        <Link href={`/search${q ? `?q=${encodeURIComponent(q)}` : ""}`} className="btn">조문 내용 검색</Link>
      </form>
      <div className="mb-5 flex flex-wrap gap-2">
        {chip("/regulations", "전체", !inst && !kind)}
        {insts?.map((i) => chip(`/regulations?inst=${i.code}`, `${i.name} ${i.works}`, inst === i.code))}
        {chip("/regulations?kind=law", "법령", kind === "law")}
      </div>
      {!works?.length ? (
        <p className="card p-6 text-sm text-[var(--muted)]">해당하는 규정이 없습니다.</p>
      ) : (
        <ul className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {works.map((w) => (
            <li key={w.id}>
              <Link href={workHref(w.id)} className="card flex items-start justify-between gap-3 p-4 text-[var(--ink)] hover:no-underline hover:border-[var(--accent-line)]">
                <div>
                  <div className="flex flex-wrap items-center gap-2 font-semibold">
                    {w.title}
                    <AbolishBadge status={w.status} abolishedOn={w.abolished_on} />
                  </div>
                  <div className="mt-1 text-xs text-[var(--muted)]">{w.institution ?? w.kind}</div>
                </div>
                {w.version && (
                  <div className="flex shrink-0 flex-col items-end gap-1 text-xs">
                    <span className={`chip ${w.version.version_state === "CURRENT" ? "chip-green" : "chip-amber"}`}>{STATE_LABEL[w.version.version_state]}</span>
                    <span className="text-[var(--muted)]">시행 {fmtDate(w.version.effective_from)}</span>
                  </div>
                )}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
