import { Columns3, Download, MessageSquare } from "lucide-react";
import Link from "next/link";
import { redirect } from "next/navigation";
import { DiffOnly, InstitutionChips, ItemSelect, TopicSelect } from "@/components/compare/Controls";
import { compareHref, parseCompareQuery, type CompareQuery } from "@/components/compare/query";
import { Crumbs } from "@/components/shell/Breadcrumbs";
import { buttonClass } from "@/components/ui/button";
import { cn } from "@/components/ui/cn";
import { EmptyState } from "@/components/ui/empty-state";
import { LinkSegmented } from "@/components/ui/link-segmented";
import { iconStroke } from "@/components/ui/styles";
import { Table, TBody, Td, Th, THead, Tr } from "@/components/ui/table";
import {
  apiTry, type CompareCell, type CompareData, type CompareProvisions, type ProvisionCompare, type ProvisionLine, type TopicInfo, workHref,
} from "@/lib/api";
import { fmtDate, fmtNum } from "@/lib/format";
import { ourInstitution } from "@/lib/server-inst";

/**
 * 기관 비교 (서비스 UI 개편 §4): 주제 × 기관. 항목 표(우리 기관이 첫 열, 다른 칸은 --warning 면) | 조문 나란히.
 * 규정 보기의 "나란히 보기"(?view=side&pv=)는 그 조를 근거로 한 비교값의 주제·항목으로 연다.
 */
export default async function ComparePage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  // 옛 판본 비교 주소는 규정 보기의 개정 이력 탭으로
  if (typeof sp.work === "string" && sp.work) {
    const p = new URLSearchParams({ tab: "history" });
    if (typeof sp.from === "string") p.set("from", sp.from);
    if (typeof sp.to === "string") p.set("to", sp.to);
    redirect(workHref(sp.work, `?${p}`));
  }
  const { pv, ...query } = parseCompareQuery(sp);
  const { inst: mine, insts } = await ourInstitution(undefined);

  if (pv) {
    const loc = await apiTry<ProvisionCompare>("/api/v1/provision/compare", { pv });
    if (loc) {
      const cell = loc.cells[0];
      const href = compareHref({ ...query, ours: loc.institution ?? query.ours, topic: cell?.topic ?? loc.topics[0] ?? "",
        item: cell?.item ?? "", view: cell ? "side" : "table" });
      redirect(cell ? href : `${href}${href.includes("?") ? "&" : "?"}nocell=1`);
    }
  }
  const ours = query.ours || mine || "";
  const q: CompareQuery = query;
  const topics = (await apiTry<TopicInfo[]>("/api/v1/topics", { inst: ours || undefined })) ?? [];
  const topic = topics.find((t) => t.id === query.topic);
  const instOpts = insts.map((i) => ({ code: i.code, name: i.name, works: i.works }));

  if (!topic) return <TopicIndex topics={topics} query={q} ours={ours} oursName={insts.find((i) => i.code === ours)?.name ?? null} />;

  const data = await apiTry<CompareData>("/api/v1/compare", { topic: topic.id, inst: query.inst.length ? query.inst.join(",") : undefined, ours: ours || undefined });
  const valued = (id: string) => Object.values(data?.cells[id] ?? {}).some((c) => c.status === "value");
  const item = data?.items.find((i) => i.id === query.item) ?? data?.items.find((i) => valued(i.id)) ?? data?.items[0];
  const side = query.view === "side" && item && data
    ? await apiTry<CompareProvisions>("/api/v1/compare/provisions", { topic: topic.id, item: item.id, inst: data.institutions.map((i) => i.code).join(","), ours: ours || undefined })
    : null;
  const filled = data ? Object.values(data.cells).some((row) => Object.values(row).some((c) => c.status !== "pending")) : false;
  const csv = `/api/v1/compare/export.csv?${new URLSearchParams({ topic: topic.id, ...(data ? { inst: data.institutions.map((i) => i.code).join(",") } : {}) })}`;

  return (
    <div className="max-w-[1440px]">
      <Crumbs items={[{ label: topic.label }]} />
      <div className="mb-4 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <div className="mb-1.5 text-caption text-fg-muted">기관 비교</div>
          <h1 className="text-display text-fg">{topic.label}</h1>
          <p className="mt-1.5 text-small text-fg-muted">
            {ours ? "우리 기관 기준과 다른 칸을 노란색으로 표시합니다" : "우리 기관을 고르면 그 기관과 다른 칸을 표시합니다"}
            {data?.built_at ? <> · 값 추출 <span className="num">{fmtDate(data.built_at)}</span></> : null}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <TopicSelect query={q} topics={topics.map((t) => ({ id: t.id, label: t.label }))} />
          {filled ? (
            <a href={csv} download className={buttonClass("secondary")}><Download aria-hidden="true" strokeWidth={iconStroke} />CSV로 내보내기</a>
          ) : (
            <span aria-disabled="true" className={buttonClass("secondary", "md", "pointer-events-none opacity-50")}><Download aria-hidden="true" strokeWidth={iconStroke} />CSV로 내보내기</span>
          )}
          <Link href={`/assistant?${new URLSearchParams({ q: `${topic.label} 규정은 기관마다 어떻게 다른가요?` })}`} className={buttonClass("primary")}>
            <MessageSquare aria-hidden="true" strokeWidth={iconStroke} />차이 설명 받기
          </Link>
        </div>
      </div>

      {sp.nocell === "1" ? <p className="mb-3 text-small text-fg-muted">고른 조문으로 뽑은 비교값이 아직 없어 그 규정의 주제 표를 엽니다.</p> : null}

      {data ? (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 border-b border-border-subtle pb-3">
          <InstitutionChips query={q} shown={data.institutions} insts={instOpts} />
          <div className="flex items-center gap-3">
            {query.view === "table" ? <DiffOnly query={q} /> : null}
            <LinkSegmented aria-label="보기" value={query.view} items={[
              { value: "table", label: "항목 표", href: compareHref(q, { view: "table" }) },
              { value: "side", label: "조문 나란히", href: compareHref(q, { view: "side", item: item?.id ?? "" }) },
            ]} />
          </div>
        </div>
      ) : null}

      {!data || !filled ? (
        <div className="rounded-md border border-border bg-bg-panel">
          <EmptyState icon={Columns3} title="아직 기관별 값을 뽑지 않았습니다"
            description={`${topic.label} 규정 ${fmtNum(topic.works)}건, 기관 ${fmtNum(topic.institutions)}곳을 분류했습니다. 비교 항목 ${fmtNum(topic.items)}개의 값을 뽑으면 여기에 표가 나옵니다.`}
            action={<Link href={`/regulations?${new URLSearchParams({ topic: topic.id, inst: "all" })}`} className={buttonClass("secondary")}>이 주제 규정 보기</Link>} />
        </div>
      ) : query.view === "side" && item ? (
        <SideBySide data={data} side={side} query={q} item={item} />
      ) : (
        <ItemTable data={data} diffOnly={query.diff} query={q} />
      )}
    </div>
  );
}

function TopicIndex({ topics, query, ours, oursName }: { topics: TopicInfo[]; query: CompareQuery; ours: string; oursName: string | null }) {
  return (
    <div className="max-w-[1200px]">
      <h1 className="text-display text-fg">기관 비교</h1>
      <p className="mb-6 mt-1.5 text-small text-fg-muted">주제를 고르면 같은 항목을 기관별로 나란히 봅니다{oursName ? ` · 우리 기관 ${oursName}` : ""}</p>
      {topics.length === 0 ? (
        <div className="rounded-md border border-border bg-bg-panel"><EmptyState icon={Columns3} title="주제 분류가 아직 없습니다" description="규정을 주제로 나누면 여기에서 고를 수 있습니다." /></div>
      ) : (
        <Table caption="비교 주제">
          <THead><Tr><Th>주제</Th><Th className="text-right">비교 항목</Th><Th className="text-right">규정</Th><Th className="text-right">기관</Th>{ours ? <Th className="text-right">우리 규정</Th> : null}</Tr></THead>
          <TBody>
            {topics.map((t) => (
              <Tr key={t.id} className="hover:bg-bg-hover">
                <Td>
                  <Link href={compareHref(query, { topic: t.id })} className="font-semibold text-fg hover:text-fg">{t.label}</Link>
                  <p className="mt-0.5 line-clamp-1 max-w-[56ch] text-caption font-normal text-fg-muted">{t.description}</p>
                </Td>
                <Td className="num text-right">{t.items ? fmtNum(t.items) : <span className="text-fg-muted">—</span>}</Td>
                <Td className="num text-right">{fmtNum(t.works)}</Td>
                <Td className="num text-right">{fmtNum(t.institutions)}</Td>
                {ours ? <Td className="num text-right">{fmtNum(t.ours ?? 0)}</Td> : null}
              </Tr>
            ))}
          </TBody>
        </Table>
      )}
    </div>
  );
}

function Cell({ c, ours }: { c: CompareCell | undefined; ours: boolean }) {
  if (!c || c.status === "pending") return <span className="text-small text-fg-subtle">아직 추출 전</span>;
  if (c.status === "absent") return <span className="text-small text-fg-muted">규정 없음</span>;
  return (
    <>
      <div className={cn("num text-small text-fg", ours && "font-semibold")}>{c.value}</div>
      {c.href ? <Link href={c.href} className="text-caption font-normal">{c.title} {c.label}</Link> : null}
    </>
  );
}

function ItemTable({ data, diffOnly, query }: { data: CompareData; diffOnly: boolean; query: CompareQuery }) {
  const rows = data.items.filter((it) => !diffOnly || Object.values(data.cells[it.id] ?? {}).some((c) => c.differs));
  return (
    <>
      <Table caption={`${data.topic_label} 기관별 비교`}>
        <THead>
          <Tr>
            <Th className="sticky left-0 z-[var(--z-sticky)] min-w-[180px] bg-bg-subtle">비교 항목</Th>
            {data.institutions.map((i) => <Th key={i.code} className="min-w-[160px]">{i.name}{i.ours ? " (우리)" : ""}</Th>)}
          </Tr>
        </THead>
        <TBody>
          {rows.map((it) => {
            const m = data.majority[it.id];
            return (
              <Tr key={it.id}>
                <Td className="sticky left-0 z-[var(--z-sticky)] bg-bg-subtle">
                  <Link href={compareHref(query, { view: "side", item: it.id })} className="text-small font-semibold text-fg hover:text-fg">{it.label}</Link>
                  {m ? <div className="num text-caption font-normal text-fg-muted">다수 {m.value} · {m.count}/{m.total}곳</div> : null}
                </Td>
                {data.institutions.map((i) => {
                  const c = data.cells[it.id]?.[i.code];
                  return (
                    <Td key={i.code} className={cn(c?.differs && "bg-warning-cell")}>
                      <Cell c={c} ours={i.ours} />{c?.differs ? <span className="sr-only"> (우리 기관과 다름)</span> : null}
                    </Td>
                  );
                })}
              </Tr>
            );
          })}
          {rows.length === 0 ? <Tr><Td colSpan={data.institutions.length + 1} className="py-6 text-center text-small text-fg-muted">우리 기관과 다른 항목이 없습니다</Td></Tr> : null}
        </TBody>
      </Table>
      <p className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-caption font-normal text-fg-muted">
        <span className="inline-flex items-center gap-1.5"><span aria-hidden="true" className="size-3 rounded-xs border border-warning-line bg-warning-cell" />우리 기관과 다른 값</span>
        <span>값은 조문에서 뽑아 원문 인용과 대조했습니다. 근거 조문을 눌러 확인하세요.</span>
      </p>
    </>
  );
}

function Marked({ line }: { line: ProvisionLine }) {
  const quote = line.highlights.find((m) => m.kind === "quote");
  const value = line.highlights.find((m) => m.kind === "value");
  if (!quote) return <>{line.text}</>;
  const t = line.text;
  const inner = value && value.start >= quote.start && value.end <= quote.end
    ? <>{t.slice(quote.start, value.start)}<strong className="font-semibold text-fg underline decoration-warning-solid decoration-2 underline-offset-2">{t.slice(value.start, value.end)}</strong>{t.slice(value.end, quote.end)}</>
    : t.slice(quote.start, quote.end);
  return <>{t.slice(0, quote.start)}<mark className="rounded-xs bg-mark text-inherit">{inner}</mark>{t.slice(quote.end)}</>;
}

function SideBySide({ data, side, query, item }: { data: CompareData; side: CompareProvisions | null; query: CompareQuery; item: { id: string; label: string } }) {
  // 같음/다름은 항목 표 응답(cells.differs)에서 가져온다
  const cols = (side?.institutions ?? []).map((c) => ({ ...c, differs: data.cells[item.id]?.[c.code]?.differs ?? null }));
  return (
    <section aria-labelledby="side-h">
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <h2 id="side-h" className="text-heading text-fg">{item.label} — 조문 나란히</h2>
        <ItemSelect query={query} items={data.items} />
      </div>
      <div role="region" aria-label="기관별 근거 조문" tabIndex={0} className="relative overflow-x-auto rounded-md border border-border bg-bg-panel">
        <div className="grid auto-cols-[minmax(280px,1fr)] grid-flow-col divide-x divide-border-subtle">
          {cols.map((c) => (
            <article key={c.code} className={cn("min-w-0 px-4 py-3.5", c.ours && "bg-bg-subtle")} aria-label={c.name}>
              <header className="mb-2">
                <p className="text-small font-semibold text-fg">{c.name}{c.ours ? " (우리)" : ""}</p>
                {c.href ? <Link href={c.href} className="text-caption font-normal">{c.title} {c.article?.label ?? c.label}{c.article?.heading ? ` (${c.article.heading})` : ""}</Link> : null}
                {c.status === "value" ? <p className={cn("num mt-1 text-small", c.differs ? "text-warning" : "text-fg")}>{c.value}{c.differs ? " · 우리와 다름" : ""}</p> : null}
              </header>
              {c.status === "absent" ? <p className="text-small text-fg-muted">규정 없음</p>
                : c.status === "pending" ? <p className="text-small text-fg-subtle">아직 추출 전</p>
                : (
                  <div className="flex flex-col gap-1 text-small text-fg">
                    {c.lines.map((l) => (
                      <p key={l.path} className={cn(!l.target && "text-fg-muted")}>{l.label && !l.label.startsWith("제") ? `${l.label} ` : ""}<Marked line={l} /></p>
                    ))}
                  </div>
                )}
            </article>
          ))}
        </div>
      </div>
      <p className="mt-2 text-caption font-normal text-fg-muted">노란 면은 값을 뽑은 원문 인용, 굵은 밑줄은 비교값입니다.</p>
    </section>
  );
}
