import Link from "next/link";
import { apiGet, type ReviewTask, workHref } from "@/lib/api";
import { fmtDate, TASK_LABEL } from "@/lib/format";

export default async function ReviewPage({ searchParams }: { searchParams: Promise<{ kind?: string }> }) {
  const { kind } = await searchParams;
  const tasks = (await apiGet<ReviewTask[]>("/api/v1/review-tasks", { status: "OPEN", kind })) ?? [];
  return (
    <main className="mx-auto max-w-6xl px-6 py-6">
      <h1 className="mb-1 text-2xl font-bold">검수 큐</h1>
      <p className="mb-4 text-[13px] text-[var(--muted)]">자동 판정이 불확실한 항목입니다. 처리(승인·수정)는 로그인 기능과 함께 제공됩니다.</p>
      <div className="mb-4 flex flex-wrap gap-2">
        <Link href="/review" className={`chip ${!kind ? "chip-blue" : ""}`}>전체</Link>
        {Object.entries(TASK_LABEL).map(([k, l]) => <Link key={k} href={`/review?kind=${k}`} className={`chip ${kind === k ? "chip-blue" : ""}`}>{l}</Link>)}
      </div>
      {tasks.length === 0 ? <p className="card p-6 text-sm">열린 검수 작업이 없습니다.</p> : (
        <table className="card w-full overflow-hidden text-[13px]">
          <thead className="bg-[#f7f8fa] text-left text-xs text-[var(--muted)]">
            <tr><th className="px-4 py-2.5">유형</th><th className="px-4 py-2.5">규정</th><th className="px-4 py-2.5">내용</th><th className="px-4 py-2.5">생성</th></tr>
          </thead>
          <tbody>
            {tasks.map((t) => (
              <tr key={t.id} className="border-t border-[var(--line)] align-top">
                <td className="px-4 py-2.5"><span className="chip chip-amber">{TASK_LABEL[t.kind] ?? t.kind}</span></td>
                <td className="px-4 py-2.5">{t.work_id ? <Link href={workHref(t.work_id)}>{t.work_title}</Link> : "-"}</td>
                <td className="px-4 py-2.5 font-mono text-xs text-[var(--ink-2)]">{JSON.stringify(t.detail)}</td>
                <td className="px-4 py-2.5 whitespace-nowrap text-[var(--muted)]">{fmtDate(t.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
