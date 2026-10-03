import { ClipboardCheck } from "lucide-react";
import Link from "next/link";
import { MyNameButton } from "@/components/review/MyName";
import { Numbers } from "@/components/review/Numbers";
import { ReviewTable } from "@/components/review/ReviewTable";
import { Toolbar } from "@/components/review/Toolbar";
import { apiParams, parseReviewQuery, reviewHref, type ReviewTaskList } from "@/components/review/types";
import { buttonClass } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { LinkSegmented } from "@/components/ui/link-segmented";
import { Pagination } from "@/components/ui/pagination";
import { apiGet, type Institution } from "@/lib/api";

const PAGE = 50;

/** 검수 (서비스 UI 개편 §6): 머리 · 숫자 줄 · 툴바(상태, 기관·종류·담당, 찾기) · 표(행 펼침에서 처리) · 법령 적재 대기 묶음. */
export default async function ReviewPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const query = parseReviewQuery(await searchParams);
  const [data, insts] = await Promise.all([
    apiGet<ReviewTaskList>(`/api/v1/review-tasks?${apiParams(query, PAGE)}&summary=true`),
    apiGet<Institution[]>("/api/v1/institutions").catch(() => null),
  ]);
  if (!data) return null;
  const s = data.summary ?? { open: 0, hold: 0, unassigned: 0, law_pending: 0, by_kind: {}, by_institution: {} };
  const instOpts = (insts ?? []).filter((i) => s.by_institution[i.code]).map((i) => ({ code: i.code, name: i.name, count: s.by_institution[i.code] }));
  return (
    <div className="max-w-[1440px]">
      <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-display text-fg">검수</h1>
          <p className="mt-1.5 text-small text-fg-muted">자동으로 처리하지 못한 항목을 기관 담당자가 확인합니다</p>
        </div>
        <MyNameButton />
      </div>
      <div className="mb-6"><Numbers query={query} summary={s} /></div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <LinkSegmented aria-label="상태" value={query.status} items={[
          { value: "open", label: "열림", href: reviewHref(query, { status: "open" }) },
          { value: "hold", label: "보류", href: reviewHref(query, { status: "hold" }) },
          { value: "done", label: "완료", href: reviewHref(query, { status: "done" }) },
          { value: "all", label: "전체", href: reviewHref(query, { status: "all" }) },
        ]} />
        <Toolbar query={query} insts={instOpts} />
        <Link href={reviewHref(query, { law: !query.law })} aria-pressed={query.law}
          className={buttonClass(query.law ? "primary" : "ghost", "sm", "ml-auto")}>
          법령 적재 대기 <span className="num">{s.law_pending.toLocaleString("ko-KR")}</span>
        </Link>
      </div>
      {query.law ? (
        <p className="mb-3 text-small text-fg-muted">법령 이름을 인용했지만 그 법령을 아직 law.go.kr에서 받지 않아 잇지 못한 항목입니다. 법령을 적재하면 대부분 저절로 닫힙니다.</p>
      ) : null}
      {data.items.length === 0 ? (
        <div className="rounded-md border border-border bg-bg-panel">
          <EmptyState icon={ClipboardCheck} title="해당하는 검수 작업이 없습니다" description="필터를 바꾸거나 다른 상태를 보세요."
            action={<Link href="/review" className={buttonClass("secondary")}>필터 지우기</Link>} />
        </div>
      ) : (
        <>
          <ReviewTable items={data.items} />
          <Pagination className="mt-3" page={data.page} size={data.size} total={data.total} href={(p) => reviewHref(query, { page: p })} />
        </>
      )}
    </div>
  );
}
