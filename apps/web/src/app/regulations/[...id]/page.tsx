import Link from "next/link";
import { notFound } from "next/navigation";
import { ProvisionText } from "@/components/ProvisionText";
import { LawPanel } from "@/components/LawPanel";
import { Relations } from "@/components/Relations";
import { apiGet, decodeSegments, type LawArticleDetail, type LawCite, type Provision, sourceHref, validDate, type VersionRow, type ViewData, workHref } from "@/lib/api";
import { BASIS_LABEL, fmtDate, STATE_LABEL, STATUS_LABEL, TASK_LABEL } from "@/lib/format";

const INDENT: Record<string, string> = { paragraph: "", item: "pl-5", subitem: "pl-10" };

export default async function ViewerPage({ params, searchParams }: {
  params: Promise<{ id: string[] }>; searchParams: Promise<{ as_of?: string | string[]; a?: string; law?: string }>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  const a = typeof sp.a === "string" ? sp.a : undefined;
  const as_of = validDate(sp.as_of);
  const badDate = sp.as_of !== undefined && !as_of;
  const workId = decodeSegments(id);
  const [view, versions] = await Promise.all([
    apiGet<ViewData>("/api/v1/work/view", { id: workId, as_of }),
    apiGet<VersionRow[]>("/api/v1/work/versions", { id: workId }),
  ]);
  if (!versions) notFound();
  if (badDate) {
    return <main className="mx-auto max-w-3xl px-6 py-10"><p className="card p-6">기준일 형식이 올바르지 않습니다(예: 2024-01-17). <Link href={workHref(workId)}>현행 보기</Link></p></main>;
  }
  if (!view) {
    return (
      <main className="mx-auto max-w-3xl px-6 py-10">
        <p className="card p-6">{fmtDate(as_of ?? null)}에 시행 중인 버전이 없습니다. <Link href={workHref(workId)}>현행 보기</Link></p>
      </main>
    );
  }
  const { work, version: v, provisions, refs, history, tasks } = view;
  const lawArt = typeof sp.law === "string" && /^\d+$/.test(sp.law) ? sp.law : undefined;
  const [cites, lawDetail] = await Promise.all([
    apiGet<Record<string, LawCite[]>>("/api/v1/law/citations", { version: v.id }).catch(() => null),
    lawArt ? apiGet<LawArticleDetail>(`/api/v1/law/article/${lawArt}`).catch(() => null) : Promise.resolve(null),
  ]);
  const baseQ: Record<string, string> = { ...(as_of ? { as_of } : {}), ...(a ? { a } : {}) };
  const lawPanelHref = (id: number) => `?${new URLSearchParams({ ...baseQ, law: String(id) })}`;
  const closeLawHref = `?${new URLSearchParams(baseQ)}`;
  const articles = provisions.filter((p) => p.unit === "article");
  const selected = articles.find((p) => p.path === a) ?? articles[0];
  const tops = provisions.filter((p) => ["chapter", "section", "article", "supplement", "annex"].includes(p.unit));
  const kids = (path: string): Provision[] => provisions.filter((p) => p.parent === path);
  const subtree = (path: string): Provision[] => kids(path).flatMap((k) => [k, ...subtree(k.path)]);
  const isLaw = work.id.startsWith("kr/law/");
  const title = (p: Provision) => p.unit === "supplement" ? `부칙 ${fmtDate(p.path.split("@")[1]?.slice(0, 10) ?? null)}` : `${p.label}${p.heading ? ` ${p.heading}` : ""}`;

  return (
    <main className="pb-8">
      <div className="flex flex-wrap items-center gap-1.5 px-6 pt-4 text-[13px] text-[var(--muted)]">
        <Link href={work.institution ? `/regulations?inst=${work.institution}` : "/regulations?kind=law"}>{work.institution ?? "법령"}</Link>
        <span>/</span><span className="text-[var(--ink)]">{work.title}</span>
      </div>
      <section className="card mx-6 mt-3 flex flex-wrap items-end gap-6 px-6 py-5">
        <div className="flex grow flex-col gap-2.5">
          <div className="flex flex-wrap items-baseline gap-3">
            <h1 className="text-[26px] font-bold tracking-tight">{v.title}</h1>
            {v.class_code && <span className="font-mono text-xs text-[var(--muted)]">원규분류 {v.class_code}</span>}
          </div>
          <div className="flex flex-wrap gap-2">
            <span className={`chip ${v.version_state === "CURRENT" ? "chip-green" : "chip-amber"}`}>{STATE_LABEL[v.version_state]}</span>
            <span className="chip">시행 {fmtDate(v.effective_from)} · {BASIS_LABEL[v.effective_basis]}</span>
            {v.effective_status !== "CONFIRMED" && <span className="chip chip-amber">{STATUS_LABEL[v.effective_status]}</span>}
            {v.amendment_no && <span className="chip">{v.amendment_kind ?? "개정"} · 제{v.amendment_no}호</span>}
            <span className="chip">출처 {isLaw ? "law.go.kr" : "ALIO"}</span>
            <span className={`chip ${v.validation_status === "PASSED" ? "chip-blue" : "chip-amber"}`}>{v.validation_status === "PASSED" ? "검증 통과" : "검수 필요"}</span>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <form className="flex items-center gap-2 text-[13px] text-[var(--ink-2)]">
            <label htmlFor="as_of">기준일</label>
            <input id="as_of" name="as_of" type="date" defaultValue={as_of} className="h-9 rounded-lg border border-[var(--line-strong)] px-2.5" />
            <button className="btn" type="submit">보기</button>
          </form>
          <Link className="btn" href={`/compare?work=${encodeURIComponent(work.id)}`}>연혁·비교</Link>
          {isLaw ? (
            <a className="btn btn-dark" href={v.source.url.replace("type=XML", "type=HTML")} target="_blank" rel="noreferrer">law.go.kr 원문</a>
          ) : (
            <Link className="btn btn-dark" href={sourceHref(work.id, `?${new URLSearchParams({ version: v.id, ...(selected ? { a: selected.path } : {}) })}`)}>원문 보기</Link>
          )}
        </div>
      </section>

      <div className="grid grid-cols-1 gap-4 px-6 pt-4 lg:grid-cols-[240px_minmax(0,1fr)_340px]">
        <nav aria-label="목차" className="card hidden self-start p-2 text-[13px] lg:block lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:overflow-auto">
          <div className="px-2.5 pb-2 text-xs font-semibold text-[var(--muted)]">목차</div>
          {tops.map((p) => (
            <a key={p.path} href={`?${new URLSearchParams({ ...(as_of ? { as_of } : {}), ...(p.unit === "article" ? { a: p.path } : {}) })}#${p.path}`}
              className={`block rounded-md px-2.5 py-1 text-[var(--ink-2)] hover:bg-[#ebeef2] hover:no-underline ${p.unit === "article" ? "pl-5" : "font-semibold"} ${p.path === selected?.path ? "bg-[var(--accent-soft)] text-[var(--accent)]" : ""}`}>
              {title(p)}
            </a>
          ))}
        </nav>

        <article className="card px-6 py-7 font-serif text-base leading-[1.85] md:px-9">
          {tops.map((p) => {
            if (p.unit === "chapter" || p.unit === "section") {
              return <h2 key={p.path} id={p.path} className="mb-4 mt-6 text-center font-sans text-[15px] font-semibold tracking-[0.2em] text-[var(--muted)] first:mt-0">{p.label} {p.heading}</h2>;
            }
            const on = p.path === selected?.path;
            return (
              <section key={p.path} id={p.path} className={`scroll-mt-4 py-3 ${on ? "-mx-4 rounded-xl bg-[#f5f8fe] px-4 outline outline-1 outline-[var(--accent-line)]" : ""}`}>
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <div className="font-semibold">{p.unit === "supplement" ? title(p) : `${p.label}${p.heading ? `(${p.heading})` : ""}`}</div>
                  {p.unit === "article" && !on && (
                    <a className="font-sans text-xs" href={`?${new URLSearchParams({ ...(as_of ? { as_of } : {}), a: p.path })}#${p.path}`}>관계 보기</a>
                  )}
                </div>
                {p.text && <p className={`mt-1 ${p.deleted ? "text-[var(--muted)]" : ""}`}><ProvisionText text={p.text} refs={refs[String(p.id)]} workId={work.id} asOf={as_of} cites={cites?.[String(p.id)]} lawHref={lawPanelHref} /></p>}
                {subtree(p.path).map((c) => (
                  <p key={c.path} id={c.path} className={`mt-1.5 ${INDENT[c.unit] ?? ""} ${c.deleted ? "text-[var(--muted)]" : ""}`}>
                    {c.unit !== "supp_article" ? `${c.label} ` : <strong className="font-semibold">{c.label}{c.heading ? `(${c.heading}) ` : " "}</strong>}
                    <ProvisionText text={c.text} refs={refs[String(c.id)]} workId={work.id} asOf={as_of} cites={cites?.[String(c.id)]} lawHref={lawPanelHref} />
                    {c.annotations.map((n) => <span key={n} className="note"> {n}</span>)}
                  </p>
                ))}
                {p.annotations.length > 0 && <div className="mt-1 font-sans text-xs text-[var(--muted)]">{p.annotations.join(" ")}</div>}
              </section>
            );
          })}
        </article>

        <aside className="flex flex-col gap-4 self-start lg:sticky lg:top-4">
          {lawDetail && <LawPanel d={lawDetail} closeHref={closeLawHref} />}
          {selected && <Relations pvIds={[selected.id, ...subtree(selected.path).map((c) => c.id)]} label={selected.label} workId={work.id} />}
          <section className="card p-4">
            <div className="mb-3 flex items-baseline justify-between">
              <h2 className="text-[13px] font-semibold">연혁</h2>
              <Link className="text-xs" href={`/compare?work=${encodeURIComponent(work.id)}`}>버전 비교</Link>
            </div>
            <ol className="flex flex-col gap-2 text-[13px]">
              {versions.slice(0, 8).map((x) => (
                <li key={x.id} className="flex justify-between gap-2">
                  {x.id === v.id ? <span className="font-semibold">{fmtDate(x.effective_from)} 시행</span>
                    : <Link href={x.effective_from ? `?as_of=${x.effective_from}` : "#"}>{fmtDate(x.effective_from)} 시행</Link>}
                  <span className="text-[var(--muted)]">{x.amendment_no ? `제${x.amendment_no}호 · ` : ""}{STATE_LABEL[x.version_state]}</span>
                </li>
              ))}
            </ol>
            {history.length > 0 && <p className="mt-3 text-xs text-[var(--muted)]">제정 {fmtDate(history[0].date)} · 개정 이력 {history.length}건</p>}
          </section>
          {tasks.length > 0 && (
            <section className="card p-4 text-[13px]">
              <h2 className="mb-2 font-semibold">검수 대기</h2>
              <ul className="flex flex-col gap-1">{tasks.map((t, i) => <li key={i}><span className="chip chip-amber">{TASK_LABEL[t.kind]}</span></li>)}</ul>
            </section>
          )}
        </aside>
      </div>
    </main>
  );
}
