import Link from "next/link";
import { Crumbs } from "@/components/shell/Breadcrumbs";
import { notFound } from "next/navigation";
import { AnnexList } from "@/components/AnnexList";
import { AnnexViewer } from "@/components/AnnexViewer";
import { LawPanel } from "@/components/LawPanel";
import { apiGet, type LawAnnex, type LawArticle, type LawArticleDetail, type LawSummary, workHref } from "@/lib/api";

const INDENT: Record<string, string> = { paragraph: "", item: "pl-5", subitem: "pl-10" };

export default async function LawPage({ params, searchParams }: {
  params: Promise<{ lawId: string }>; searchParams: Promise<{ a?: string; annex?: string }>;
}) {
  const { lawId: raw } = await params;
  const sp = await searchParams;
  let lawId = raw;
  try { lawId = decodeURIComponent(raw); } catch { /* 그대로 */ }
  const base = `/api/v1/law/${encodeURIComponent(lawId)}`;
  const [sum, arts, annexes] = await Promise.all([
    apiGet<LawSummary>(base), apiGet<LawArticle[]>(`${base}/articles`), apiGet<LawAnnex[]>(`${base}/annexes`),
  ]);
  if (!sum || !arts) notFound();
  const a = typeof sp.a === "string" ? sp.a : undefined;
  const annexSeq = typeof sp.annex === "string" && /^\d+$/.test(sp.annex) ? sp.annex : undefined;
  const selected = arts.find((x) => x.unit === "article" && x.path === a);
  const detail = selected ? await apiGet<LawArticleDetail>(`/api/v1/law/article/${selected.id}`) : null;
  const openAnnex = annexSeq ? (annexes ?? []).find((x) => x.seq === annexSeq) : undefined;
  const tops = arts.filter((x) => ["chapter", "section", "article", "supplement"].includes(x.unit));
  const kids = (path: string): LawArticle[] => arts.filter((x) => x.parent === path);
  const subtree = (path: string): LawArticle[] => kids(path).flatMap((k) => [k, ...subtree(k.path)]);
  const q = (extra: Record<string, string>) => `?${new URLSearchParams({ ...(a ? { a } : {}), ...(annexSeq ? { annex: annexSeq } : {}), ...extra })}`;
  const without = (key: "a" | "annex") => `?${new URLSearchParams({ ...(a && key !== "a" ? { a } : {}), ...(annexSeq && key !== "annex" ? { annex: annexSeq } : {}) })}`;
  const { law, version: v, links } = sum;
  const title = (x: LawArticle) => x.unit === "supplement" ? "부칙" : `${x.label}${x.heading ? `(${x.heading})` : ""}`;

  return (
    <div className="max-w-[1440px]">
      <Crumbs items={[{ label: law.name }]} />
      <section className="card flex flex-wrap items-end gap-6 px-6 py-5">
        <div className="flex grow flex-col gap-2.5">
          <h1 className="text-[26px] font-bold tracking-tight">{law.name}</h1>
          {v && <p className="text-[13px] text-[var(--ink-2)]">{v.edition_line}</p>}
          <div className="flex flex-wrap gap-2">
            <span className={`chip ${law.status === "현행" ? "chip-green" : "chip-amber"}`}>{law.status}</span>
            {law.kind && <span className="chip">{law.kind}</span>}
            {law.ministry && <span className="chip">{law.ministry}</span>}
            {law.name_abbr && <span className="chip">약칭 {law.name_abbr}</span>}
            <span className="chip">출처 law.go.kr</span>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {sum.work_id && <Link className="btn" href={workHref(sum.work_id)}>규정 뷰어에서 보기</Link>}
          {links.archive && <a className="btn" href={links.archive} target="_blank" rel="noreferrer">보관 원본 XML</a>}
          <a className="btn btn-dark" href={links.law_go} target="_blank" rel="noreferrer">law.go.kr 원문</a>
        </div>
      </section>

      <div className="grid grid-cols-1 gap-4 pt-4 lg:grid-cols-[240px_minmax(0,1fr)_380px]">
        <nav aria-label="목차" className="card hidden self-start p-2 text-[13px] lg:block lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:overflow-auto">
          <div className="px-2.5 pb-2 text-xs font-semibold text-[var(--muted)]">목차</div>
          {tops.map((x) => (
            <a key={x.path} href={`${x.unit === "article" ? q({ a: x.path }) : ""}#${x.path}`}
              className={`block rounded-md px-2.5 py-1 text-[var(--ink-2)] hover:bg-bg-hover hover:no-underline ${x.unit === "article" ? "pl-5" : "font-semibold"} ${x.path === selected?.path ? "bg-[var(--accent-soft)] text-[var(--accent)]" : ""}`}>
              {x.unit === "chapter" || x.unit === "section" ? `${x.label} ${x.heading ?? ""}` : title(x)}
            </a>
          ))}
        </nav>

        <article className="card px-6 py-7 font-serif text-base leading-[1.85] md:px-9">
          {tops.map((x) => {
            if (x.unit === "chapter" || x.unit === "section") {
              return <h2 key={x.path} id={x.path} className="mb-4 mt-6 text-center font-sans text-[15px] font-semibold tracking-[0.2em] text-[var(--muted)] first:mt-0">{x.label} {x.heading}</h2>;
            }
            const on = x.path === selected?.path;
            return (
              <section key={x.path} id={x.path} className={`scroll-mt-4 py-3 ${on ? "-mx-4 rounded-md bg-accent-soft/50 px-4 outline outline-1 outline-[var(--accent-line)]" : ""}`}>
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <div className="font-semibold">{title(x)}</div>
                  {x.unit === "article" && !on && <Link className="font-sans text-xs" href={`${q({ a: x.path })}#${x.path}`} scroll={false}>인용 보기</Link>}
                </div>
                {x.text && <p className={`mt-1 ${x.deleted ? "text-[var(--muted)]" : ""}`}>{x.text}</p>}
                {subtree(x.path).map((c) => <p key={c.path} id={c.path} className={`mt-1.5 ${INDENT[c.unit] ?? ""}`}>{c.label} {c.text}</p>)}
              </section>
            );
          })}
        </article>

        <aside className="flex flex-col gap-4 self-start lg:sticky lg:top-4">
          {openAnnex && <AnnexViewer annex={openAnnex} closeHref={without("annex")} />}
          {detail && <LawPanel d={detail} closeHref={without("a")} showLawLink={false} />}
          <AnnexList annexes={annexes ?? []} hrefFor={(seq) => q({ annex: seq })} />
          {sum.past_versions.length > 0 && (
            <section className="card p-4 text-[13px]">
              <h2 className="mb-2 font-semibold">지난 판본 <span className="text-xs font-normal text-[var(--muted)]">판본 정보만 보관</span></h2>
              <ol className="flex flex-col gap-1.5">
                {sum.past_versions.map((p) => (
                  <li key={p.mst}>{p.url ? <a href={p.url} target="_blank" rel="noreferrer">{p.edition_line}</a> : p.edition_line}</li>
                ))}
              </ol>
            </section>
          )}
        </aside>
      </div>
    </div>
  );
}
