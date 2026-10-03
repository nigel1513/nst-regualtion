import { Columns3, SearchX } from "lucide-react";
import Link from "next/link";
import { FilterRail } from "@/components/regulations/FilterRail";
import { parseRegQuery, regHref, type RegQuery } from "@/components/regulations/query";
import { GroupedTable, RegulationTable } from "@/components/regulations/RegulationTable";
import { SortSelect } from "@/components/regulations/SortSelect";
import { buttonClass } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { LinkSegmented } from "@/components/ui/link-segmented";
import { Pagination } from "@/components/ui/pagination";
import { iconStroke } from "@/components/ui/styles";
import { apiGet, type RegulationsResult } from "@/lib/api";
import { fmtNum } from "@/lib/format";
import { ourInstitution } from "@/lib/server-inst";

const PAGE = 50;

/** 규정 찾기 (서비스 UI 개편 §3): 왼쪽 필터 레일 220px | 표(목록 / 기관별 묶기), 정렬, 페이지. 거르기는 서버가 한다. */
export default async function RegulationsPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const parsed = parseRegQuery(sp);
  const { inst: ours, insts } = await ourInstitution(undefined);
  const query: RegQuery = { ...parsed, inst: parsed.instSet ? parsed.inst : ours ? [ours] : [] };
  const group = query.view === "group";
  const params = new URLSearchParams();
  if (query.q) params.set("q", query.q);
  query.inst.forEach((i) => params.append("inst", i));
  query.topic.forEach((t) => params.append("topic", t));
  query.kind.forEach((k) => params.append("kind", k));
  params.set("status", query.status);
  if (query.sort) params.set("sort", query.sort);
  params.set("page", group ? "1" : String(query.page));
  params.set("size", group ? "500" : String(PAGE));
  const data = await apiGet<RegulationsResult>(`/api/v1/regulations?${params}`);
  if (!data) return null;
  const withData = insts.filter((i) => i.works > 0).length;
  const shownInsts = query.inst.length ? query.inst.length : data.facets.institution.filter((f) => f.count > 0).length;
  const compareHref = `/compare?${new URLSearchParams({ ...(query.topic[0] ? { topic: query.topic[0] } : {}), ...(query.q ? { q: query.q } : {}) })}`;
  return (
    <div className="max-w-[1280px]">
      <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-display text-fg">규정 찾기</h1>
          <p className="mt-1.5 text-small text-fg-muted">
            {query.q ? <>‘{query.q}’ · </> : null}
            {query.inst.length ? `${fmtNum(withData)}개 기관 중 ${fmtNum(shownInsts)}곳` : `${fmtNum(shownInsts)}개 기관`} · 규정 <span className="num">{fmtNum(data.total)}</span>건
          </p>
        </div>
        <Link href={compareHref} className={buttonClass("primary", "md", "self-start sm:self-auto")}>
          <Columns3 aria-hidden="true" strokeWidth={iconStroke} />찾은 규정 기관별로 비교
        </Link>
      </div>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[220px_minmax(0,1fr)] lg:gap-7">
        <aside aria-label="필터">
          <FilterRail query={query} ours={ours} facets={data.facets} topicsAvailable={data.topics_available} />
        </aside>
        <section aria-label="찾은 규정" className="min-w-0">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <LinkSegmented aria-label="보기" value={query.view} items={[
              { value: "list", label: "목록", href: regHref(query, { view: "list" }) },
              { value: "group", label: "기관별 묶기", href: regHref(query, { view: "group" }) },
            ]} />
            <SortSelect query={query} current={data.sort} />
          </div>
          {data.items.length === 0 ? (
            <div className="rounded-md border border-border bg-bg-panel">
              <EmptyState icon={SearchX} title="맞는 규정이 없습니다" description="검색어를 줄이거나 필터를 풀어 보세요."
                action={<Link href={regHref({ ...query, q: "", topic: [], kind: [], status: "current" })} className={buttonClass("secondary")}>필터 지우기</Link>} />
            </div>
          ) : group ? (
            <GroupedTable rows={data.items} topics={data.topics_available} ours={ours} />
          ) : (
            <>
              <RegulationTable rows={data.items} topics={data.topics_available} />
              <Pagination className="mt-3" page={data.page} size={data.size} total={data.total} href={(p) => regHref(query, { page: p })} />
            </>
          )}
        </section>
      </div>
    </div>
  );
}
