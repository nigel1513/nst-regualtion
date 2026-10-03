import { FileText, GitCompareArrows, MessageSquare, Paperclip } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { AbolishBadge } from "@/components/AbolishBadge";
import { GraphMap } from "@/components/GraphMap";
import { LawPanel } from "@/components/LawPanel";
import { ProvisionText } from "@/components/ProvisionText";
import { RegAnnexCard } from "@/components/RegAnnexCard";
import { Relations } from "@/components/Relations";
import { Crumbs } from "@/components/shell/Breadcrumbs";
import { Badge } from "@/components/ui/badge";
import { buttonClass } from "@/components/ui/button";
import { cn } from "@/components/ui/cn";
import { EmptyState } from "@/components/ui/empty-state";
import { InstitutionMark } from "@/components/ui/institution-mark";
import { iconStroke } from "@/components/ui/styles";
import { LinkTabs } from "@/components/ui/tabs";
import { DiffText } from "@/components/viewer/DiffText";
import { SimilarRail } from "@/components/viewer/SimilarRail";
import { TrackRecent } from "@/components/viewer/TrackRecent";
import {
  apiGet, type DiffData, decodeSegments, type Institution, type LawArticleDetail, type LawCite, type Provision, sourceHref,
  validDate, type VersionRow, type ViewData, type Work, type WorkStatusFields, workHref,
} from "@/lib/api";
import { CHANGE_LABEL, cleanHeading, fmtDate, pathLabel, STATE_LABEL, STATUS_LABEL, TASK_LABEL } from "@/lib/format";

const INDENT: Record<string, string> = { paragraph: "", item: "pl-5", subitem: "pl-10" };
const TABS = ["text", "history", "graph", "annex"] as const;
type Tab = (typeof TABS)[number];
type SP = { as_of?: string | string[]; a?: string; law?: string; tab?: string; from?: string; to?: string; notes?: string };

/** 규정 보기 (서비스 UI 개편 §3): 머리 · 탭(본문 | 개정 이력 | 관계도 | 별표·서식) · 조문 목차 | 본문 | 오른쪽 레일. */
export default async function ViewerPage({ params, searchParams }: { params: Promise<{ id: string[] }>; searchParams: Promise<SP> }) {
  const { id } = await params;
  const sp = await searchParams;
  const a = typeof sp.a === "string" ? sp.a : undefined;
  const as_of = validDate(sp.as_of);
  const tab: Tab = TABS.includes(sp.tab as Tab) ? (sp.tab as Tab) : "text";
  const workId = decodeSegments(id);
  const [view, versions, insts] = await Promise.all([
    apiGet<ViewData>("/api/v1/work/view", { id: workId, as_of }),
    apiGet<VersionRow[]>("/api/v1/work/versions", { id: workId }),
    apiGet<Institution[]>("/api/v1/institutions").catch(() => null),
  ]);
  if (!versions) notFound();
  if (sp.as_of !== undefined && !as_of) {
    return <Notice workId={workId} text="기준일 형식이 올바르지 않습니다 (예: 2024-01-17)." />;
  }
  if (!view) return <Notice workId={workId} text={`${fmtDate(as_of ?? null)}에 시행 중인 판본이 없습니다.`} />;

  const { work, version: v, provisions, refs, history, tasks } = view;
  const ws = work as Work & WorkStatusFields;
  const instName = insts?.find((i) => i.code === work.institution)?.name ?? null;
  const isLaw = work.id.startsWith("kr/law/") || work.id.startsWith("kr/admrul/");
  const lawArt = typeof sp.law === "string" && /^\d+$/.test(sp.law) ? sp.law : undefined;
  const [cites, lawDetail] = await Promise.all([
    apiGet<Record<string, LawCite[]>>("/api/v1/law/citations", { version: v.id }).catch(() => null),
    lawArt ? apiGet<LawArticleDetail>(`/api/v1/law/article/${lawArt}`).catch(() => null) : Promise.resolve(null),
  ]);

  const q = (extra: Record<string, string | undefined>) => {
    const base: Record<string, string | undefined> = { tab: tab === "text" ? undefined : tab, as_of, a, ...extra };
    const p = new URLSearchParams(Object.entries(base).filter(([, x]) => x) as [string, string][]);
    return `?${p}`;
  };
  const lawPanelHref = (artId: number) => q({ law: String(artId) });
  const articles = provisions.filter((p) => p.unit === "article");
  const selected = articles.find((p) => p.path === a) ?? articles[0];
  const tops = provisions.filter((p) => ["chapter", "section", "article", "supplement", "annex"].includes(p.unit));
  const annexes = provisions.filter((p) => p.unit === "annex");
  const kids = (path: string): Provision[] => provisions.filter((p) => p.parent === path);
  const subtree = (path: string): Provision[] => kids(path).flatMap((k) => [k, ...subtree(k.path)]);
  const supTitle = (p: Provision) => `부칙 ${fmtDate(p.path.split("@")[1]?.slice(0, 10) ?? null)}`;
  const head = (p: Provision) => cleanHeading(p.heading);
  const tocLabel = (p: Provision) => (p.unit === "supplement" ? supTitle(p) : `${p.label}${head(p) ? ` ${head(p)}` : ""}`);
  const askHref = `/assistant?${new URLSearchParams({ q: `${work.title} `, work: work.id })}`;
  const text = (p: Provision) => (
    <ProvisionText text={p.text} refs={refs[String(p.id)]} workId={work.id} asOf={as_of} cites={cites?.[String(p.id)]} lawHref={lawPanelHref} />
  );

  const toc = (
    <nav aria-label="조문 목차" className="hidden self-start xl:sticky xl:top-[72px] xl:block xl:max-h-[calc(100dvh-96px)] xl:overflow-y-auto">
      <ol className="flex flex-col gap-px">
        {tops.map((p) => {
          const head = p.unit === "chapter" || p.unit === "section";
          const on = p.path === selected?.path;
          return (
            <li key={p.path}>
              <Link href={`${q(p.unit === "article" ? { a: p.path } : {})}#${p.path}`} scroll={!head && p.unit !== "article"}
                className={cn("block truncate rounded-sm px-2 py-1 text-small no-underline hover:no-underline",
                  head ? "mt-2 text-caption font-semibold text-fg-muted" : on ? "bg-bg-active font-medium text-fg hover:text-fg" : "text-fg-muted hover:bg-bg-hover hover:text-fg")}>
                {tocLabel(p)}
              </Link>
            </li>
          );
        })}
      </ol>
    </nav>
  );

  return (
    <div className="max-w-[1440px]">
      <Crumbs items={[...(instName ? [{ label: instName, href: `/regulations?inst=${work.institution}` }] : isLaw ? [{ label: "법령", href: "/laws" }] : []), { label: work.title }]} />
      {selected && tab === "text" ? (
        <TrackRecent href={workHref(work.id, `?a=${encodeURIComponent(selected.path)}#${selected.path}`)} title={work.title}
          label={`${selected.label}${selected.heading ? ` ${selected.heading}` : ""}`} inst={work.institution} />
      ) : null}

      <header className="mb-5">
        <div className="mb-1.5 flex items-center gap-1.5 text-caption text-fg-muted">
          {work.institution ? <InstitutionMark code={work.institution} full /> : null}
          <span>{instName ?? (isLaw ? "법령" : "")}</span>
        </div>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <h1 className="text-display break-keep text-fg">{v.title}</h1>
          <div className="flex flex-wrap items-center gap-2">
            <span className="num mr-1 text-small text-fg-muted">{fmtDate(v.effective_from)} 시행 판본</span>
            <Link href={q({ tab: "history", a: undefined })} className={buttonClass("secondary")}>
              <GitCompareArrows aria-hidden="true" strokeWidth={iconStroke} />판본 비교
            </Link>
            {isLaw ? (
              <a href={v.source.url.replace("type=XML", "type=HTML")} target="_blank" rel="noreferrer" className={buttonClass("secondary")}>
                <FileText aria-hidden="true" strokeWidth={iconStroke} />law.go.kr 원문
              </a>
            ) : (
              <Link href={sourceHref(work.id, `?${new URLSearchParams({ version: v.id, ...(selected ? { a: selected.path } : {}) })}`)} className={buttonClass("secondary")}>
                <FileText aria-hidden="true" strokeWidth={iconStroke} />원문 PDF
              </Link>
            )}
            <Link href={askHref} className={buttonClass("primary")}>
              <MessageSquare aria-hidden="true" strokeWidth={iconStroke} />이 규정에 묻기
            </Link>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          <Badge tone={v.version_state === "CURRENT" ? "success" : "warning"}>{STATE_LABEL[v.version_state]}</Badge>
          <AbolishBadge status={ws.status} abolishedOn={ws.abolished_on} />
          {v.effective_status !== "CONFIRMED" ? <Badge tone="warning">{STATUS_LABEL[v.effective_status]}</Badge> : null}
          {v.amendment_no ? <Badge>{v.amendment_kind ?? "개정"} 제{v.amendment_no}호</Badge> : null}
          {v.validation_status !== "PASSED" ? <Badge tone="warning">검수 필요</Badge> : null}
          {tasks.length > 0 ? <span className="text-caption text-fg-muted">검수 대기 {tasks.map((t) => TASK_LABEL[t.kind] ?? t.kind).join(", ")}</span> : null}
        </div>
        {ws.status === "ABOLISHED" ? (
          <p className="mt-2 text-small text-danger">{fmtDate(ws.abolished_on ?? null)}부터 ALIO 목록에 없어 폐지로 확인된 규정입니다. 현행 검색에서 빠지며, 과거 기준일 조회용으로 보존합니다.</p>
        ) : null}
      </header>

      <LinkTabs aria-label="규정 보기" value={tab} className="mb-6" items={[
        { value: "text", label: "본문", href: q({ tab: undefined }) },
        { value: "history", label: "개정 이력", href: q({ tab: "history" }), count: versions.length },
        { value: "graph", label: "관계도", href: q({ tab: "graph" }) },
        { value: "annex", label: "별표·서식", href: q({ tab: "annex" }), count: annexes.length },
      ]} />

      {tab === "text" ? (
        <div className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_280px] xl:grid-cols-[180px_minmax(0,1fr)_280px] xl:gap-6 min-[1440px]:grid-cols-[200px_minmax(0,1fr)_300px] min-[1440px]:gap-7">
          {toc}
          <article className="min-w-0 max-w-[72ch] text-long text-fg">
            {tops.map((p) => {
              if (p.unit === "chapter" || p.unit === "section") {
                return <h2 key={p.path} id={p.path} className="mb-2 mt-8 scroll-mt-20 text-small font-semibold text-fg-muted first:mt-0">{p.label} {head(p)}</h2>;
              }
              const on = p.path === selected?.path;
              return (
                <section key={p.path} id={p.path} className={cn("-mx-3 scroll-mt-20 rounded-md px-3 py-3", on && "bg-bg-subtle")}>
                  <h3 className="text-long font-semibold">
                    {p.unit === "article" ? (
                      <Link href={`${q({ a: p.path })}#${p.path}`} scroll={false} className="text-fg no-underline hover:text-fg hover:underline">
                        {p.label}{p.heading ? ` (${p.heading})` : ""}
                      </Link>
                    ) : p.unit === "supplement" ? supTitle(p) : `${p.label}${head(p) ? ` ${head(p)}` : ""}`}
                  </h3>
                  {p.unit === "annex" ? (
                    <RegAnnexCard workId={work.id} versionId={v.id} path={p.path} label={p.label} heading={p.heading}>{text(p)}</RegAnnexCard>
                  ) : p.text ? <p className={cn("mt-1", p.deleted && "text-fg-muted")}>{text(p)}</p> : null}
                  {subtree(p.path).map((c) => (
                    <p key={c.path} id={c.path} className={cn("mt-1.5 scroll-mt-20", INDENT[c.unit], c.deleted && "text-fg-muted")}>
                      {c.unit !== "supp_article" ? `${c.label} ` : <strong className="font-semibold">{c.label}{c.heading ? `(${c.heading}) ` : " "}</strong>}
                      {text(c)}
                      {c.annotations.map((n) => <span key={n} className="note"> {n}</span>)}
                    </p>
                  ))}
                  {p.annotations.length > 0 ? <p className="mt-1 text-caption font-normal text-fg-muted">{p.annotations.join(" ")}</p> : null}
                </section>
              );
            })}
          </article>
          <aside className="flex flex-col gap-6 self-start lg:sticky lg:top-[72px]">
            {lawDetail ? <LawPanel d={lawDetail} closeHref={q({ law: undefined })} /> : null}
            {selected && !isLaw ? <SimilarRail key={selected.id} pvId={selected.id} label={selected.label} /> : null}
          </aside>
        </div>
      ) : null}

      {tab === "graph" ? (
        <div className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_320px] xl:grid-cols-[180px_minmax(0,1fr)_320px] xl:gap-6 min-[1440px]:grid-cols-[200px_minmax(0,1fr)_340px]">
          {toc}
          {selected ? (
            <>
              <div className="min-w-0"><GraphMap key={selected.id} pvId={selected.id} label={`${selected.label}${selected.heading ? ` (${selected.heading})` : ""}`} /></div>
              <Relations key={selected.id} pvIds={[selected.id, ...subtree(selected.path).map((c) => c.id)]} label={selected.label} workId={work.id} />
            </>
          ) : <p className="text-small text-fg-muted">조문이 없습니다.</p>}
        </div>
      ) : null}

      {tab === "annex" ? (
        annexes.length === 0 ? (
          <div className="rounded-md border border-border bg-bg-panel"><EmptyState icon={Paperclip} title="별표·서식이 없습니다" description="이 판본에는 별표나 서식이 붙어 있지 않습니다." /></div>
        ) : (
          <div className="flex max-w-[960px] flex-col gap-8">
            {annexes.map((p) => (
              <section key={p.path} id={p.path} aria-label={p.label} className="scroll-mt-20">
                <h2 className="text-heading text-fg">{p.label}{head(p) ? ` ${head(p)}` : ""}</h2>
                <RegAnnexCard workId={work.id} versionId={v.id} path={p.path} label={p.label} heading={p.heading}>{text(p)}</RegAnnexCard>
              </section>
            ))}
          </div>
        )
      ) : null}

      {tab === "history" ? <History workId={work.id} current={v.id} versions={versions} history={history} sp={sp} q={q}
        articleLabels={Object.fromEntries(provisions.filter((p) => !p.path.includes(".")).map((p) => [p.path, p.label]))} /> : null}
    </div>
  );
}

function Notice({ workId, text }: { workId: string; text: string }) {
  return (
    <div className="max-w-[720px] rounded-md border border-border bg-bg-panel px-5 py-4 text-body">
      {text} <Link href={workHref(workId)}>현행 판본 보기</Link>
    </div>
  );
}

/** 개정 이력 탭: 판본 타임라인 | 고른 두 판본의 바뀐 조문 (삭제 빨강 취소선 · 추가 초록). */
async function History({ workId, current, versions, history, sp, q, articleLabels }: {
  workId: string; current: string; versions: VersionRow[]; history: ViewData["history"]; sp: SP;
  q: (extra: Record<string, string | undefined>) => string; articleLabels: Record<string, string>;
}) {
  const notes = sp.notes === "1";
  const idx = Math.max(0, versions.findIndex((x) => x.id === current));
  const toId = (typeof sp.to === "string" && versions.some((x) => x.id === sp.to)) ? sp.to : versions[idx]?.id;
  const toIdx = versions.findIndex((x) => x.id === toId);
  const fromId = (typeof sp.from === "string" && versions.some((x) => x.id === sp.from)) ? sp.from : versions[toIdx + 1]?.id;
  const diff = fromId && toId && fromId !== toId ? await apiGet<DiffData>("/api/v1/diff", { from: fromId, to: toId }).catch(() => null) : null;
  const all = diff?.changes.filter((c) => !["chapter", "section"].includes(c.unit)) ?? [];
  const noteOnly = all.filter((c) => c.kind === "ANNOTATION_ONLY").length;
  const shown = notes ? all : all.filter((c) => c.kind !== "ANNOTATION_ONLY");
  // 항·호만 바뀌면 "①"만 보이므로 소속 조를 앞에 붙인다
  const where = (c: (typeof all)[number], s: { label: string; heading: string | null }) => {
    if (!c.path.includes(".")) return `${s.label}${cleanHeading(s.heading) ? ` (${cleanHeading(s.heading)})` : ""}`;
    const art = c.path.split(".")[0];
    return `${articleLabels[art] ?? pathLabel(art)} ${s.label}`;
  };
  const label = (x: VersionRow) => `${fmtDate(x.effective_from)} 시행${x.amendment_no ? ` · 제${x.amendment_no}호` : ""}`;
  return (
    <div className="grid grid-cols-1 gap-8 lg:grid-cols-[260px_minmax(0,1fr)]">
      <aside aria-label="판본" className="self-start">
        <h2 className="mb-2 text-caption text-fg-muted">판본 {versions.length}개</h2>
        <ol className="border-l border-border">
          {versions.map((x, i) => {
            const on = x.id === toId;
            const prev = versions[i + 1];
            return (
              <li key={x.id} className="relative pb-3 pl-4 last:pb-0">
                <span aria-hidden="true" className={cn("absolute -left-[4.5px] top-[7px] size-2 rounded-full border", on ? "border-fg bg-fg" : "border-border-strong bg-bg")} />
                <Link href={q({ tab: "history", to: x.id, from: prev?.id, a: undefined })} scroll={false}
                  className={cn("num block text-small no-underline hover:no-underline", on ? "font-semibold text-fg hover:text-fg" : "text-fg-muted hover:text-fg")}>
                  {label(x)}
                </Link>
                <span className="text-caption font-normal text-fg-muted">
                  {x.amendment_kind ?? (i === versions.length - 1 ? "최초" : "개정")} · {STATE_LABEL[x.version_state]}
                  {x.effective_from ? <> · <Link href={workHref(workId, `?as_of=${x.effective_from}`)}>이 판본 보기</Link></> : null}
                </span>
              </li>
            );
          })}
        </ol>
        {history.length > 0 ? (
          <p className="mt-4 text-caption font-normal text-fg-muted">원문 개정 이력 {history.length}건 · 제정 {fmtDate(history[0].date)}</p>
        ) : null}
      </aside>
      <section aria-labelledby="diff-h" className="min-w-0">
        {!diff ? (
          <div className="rounded-md border border-border bg-bg-panel">
            <EmptyState icon={GitCompareArrows} title="비교할 이전 판본이 없습니다" description="처음 수집한 판본입니다." />
          </div>
        ) : (
          <>
            <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
              <h2 id="diff-h" className="text-heading text-fg">
                <span className="num">{fmtDate(diff.from.effective_from)}</span> → <span className="num">{fmtDate(diff.to.effective_from)}</span>
              </h2>
              <span className="flex items-center gap-3 text-small text-fg-muted">
                <span className="num">바뀐 조항 {shown.length}개</span>
                {noteOnly > 0 ? (
                  <Link href={q({ tab: "history", from: fromId, to: toId, a: undefined, notes: notes ? undefined : "1" })} scroll={false}>
                    {notes ? "주석 변경 숨기기" : `주석만 바뀐 ${noteOnly}개도 보기`}
                  </Link>
                ) : null}
              </span>
            </div>
            {shown.length === 0 ? <p className="text-small text-fg-muted">내용이 바뀐 조항이 없습니다.</p> : (
              <ol className="overflow-hidden rounded-md border border-border bg-bg-panel">
                {shown.map((c) => {
                  const s = c.to ?? c.from!;
                  return (
                    <li key={c.provision_id} className="border-b border-border-subtle px-4 py-3 last:border-0">
                      <div className="mb-1 flex flex-wrap items-center gap-2">
                        <span className="text-small font-semibold text-fg">{where(c, s)}</span>
                        <Badge tone={c.kind === "DELETED" ? "danger" : c.kind === "ADDED" ? "success" : "neutral"}>{CHANGE_LABEL[c.kind]}</Badge>
                        {c.moved && c.kind !== "RENUMBERED" ? <Badge>조 이동</Badge> : null}
                        {c.kind !== "DELETED" ? <Link href={workHref(workId, `?a=${encodeURIComponent(c.path.split(".")[0])}#${c.path}`)} className="ml-auto text-caption font-normal">본문에서 보기</Link> : null}
                      </div>
                      <p className="text-long text-fg">
                        {c.kind === "ADDED" ? <ins className="rounded-xs bg-success-soft text-success no-underline">{c.to?.text}</ins>
                          : c.kind === "DELETED" ? <del className="rounded-xs bg-danger-soft text-danger">{c.from?.text}</del>
                          : <DiffText from={c.from?.text ?? ""} to={c.to?.text ?? ""} />}
                      </p>
                    </li>
                  );
                })}
              </ol>
            )}
          </>
        )}
      </section>
    </div>
  );
}
