import Link from "next/link";
import { AlertActions } from "@/components/AlertActions";
import { type Alert, type AlertDetail, apiGet, workHref } from "@/lib/api";
import { fmtDate, REL_LABEL } from "@/lib/format";

const SEV = { HIGH: ["높음", "chip-red"], MEDIUM: ["중간", "chip-amber"], LOW: ["낮음", ""] } as const;
const CHANGE: Record<string, string> = { MODIFIED: "개정", DELETED: "삭제", RENUMBERED: "번호 이동", ADDED: "신설" };
const STATUS: Record<string, string> = { NEW: "신규", ACKED: "확인함", ACTION_REQUIRED: "조치 필요", NO_ACTION: "조치 불필요", RESOLVED: "완료" };
const TABS = [["open", "처리 필요"], ["done", "완료"]] as const;

function title(a: Alert, side: "cause" | "affected") {
  return (side === "cause" ? a.cause_title : a.affected_title) ?? (side === "cause" ? a.cause_work_id : a.affected_work_id).split("/").pop();
}

export default async function AlertsPage({ searchParams }: { searchParams: Promise<{ status?: string; id?: string }> }) {
  const { status = "open", id } = await searchParams;
  const tab = status === "done" ? "done" : "open";
  const list = (await apiGet<Alert[]>("/api/v1/alerts", { status: tab })) ?? [];
  const selId = id && /^\d+$/.test(id) ? id : list[0]?.id?.toString();
  const sel = selId ? await apiGet<AlertDetail>(`/api/v1/alerts/${selId}`) : null;
  return (
    <main className="mx-auto max-w-7xl px-6 py-6">
      <h1 className="mb-1 text-2xl font-bold">개정 알림함</h1>
      <p className="mb-4 text-[13px] text-[var(--muted)]">법령·상위 규정이 바뀌어 검토가 필요한 조항입니다. 자동 탐지 결과이며 법적 판단이 아닙니다.</p>
      <div className="mb-4 flex gap-2">
        {TABS.map(([k, l]) => <Link key={k} href={`/alerts?status=${k}`} className={`chip ${tab === k ? "chip-blue" : ""}`}>{l}</Link>)}
      </div>
      {list.length === 0 ? <p className="card p-6 text-sm">{tab === "open" ? "처리할 개정 알림이 없습니다." : "완료된 알림이 없습니다."}</p> : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,380px)_minmax(0,1fr)]">
          <ul className="flex flex-col gap-2" aria-label="알림 목록">
            {list.map((a) => (
              <li key={a.id}>
                <Link href={`/alerts?status=${tab}&id=${a.id}`} aria-current={String(a.id) === selId ? "true" : undefined}
                  className={`card block p-3.5 hover:no-underline ${String(a.id) === selId ? "border-[var(--accent)] bg-[var(--accent-soft)]" : ""}`}>
                  <div className="mb-1 flex items-center gap-2 text-xs">
                    <span className={`chip ${SEV[a.severity][1]}`}>{SEV[a.severity][0]}</span>
                    <span className="text-[var(--muted)]">{a.impact_kind}</span>
                  </div>
                  <p className="text-sm font-semibold text-[var(--ink)]">{title(a, "cause")} {CHANGE[a.cause_change] ?? a.cause_change} → {title(a, "affected")} {a.affected_path}</p>
                  <p className="mt-0.5 text-xs text-[var(--muted)]">{STATUS[a.status] ?? a.status} · {fmtDate(a.created_at)}{a.hops > 1 ? " · 위임 2단계" : ""}</p>
                </Link>
              </li>
            ))}
          </ul>
          {sel && (
            <section className="card flex flex-col gap-4 p-5" aria-label="알림 상세">
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className={`chip ${SEV[sel.severity][1]}`}>심각도 {SEV[sel.severity][0]}</span>
                <span className="chip">{REL_LABEL[sel.rel_type] ?? sel.rel_type}({sel.rel_type})</span>
                <span className="chip">{STATUS[sel.status] ?? sel.status}</span>
              </div>
              <h2 className="text-lg font-bold">{title(sel, "cause")} {CHANGE[sel.cause_change] ?? sel.cause_change}이 {title(sel, "affected")} {sel.affected_path}에 영향</h2>
              <p className="text-[13px] text-[var(--ink-2)]">
                원인: <Link href={workHref(sel.cause_work_id)}>{title(sel, "cause")}</Link> {sel.cause_path} · 버전 {sel.cause_version_id.split("@")[1]}
                {sel.recipients.length > 0 && <> · 담당: {sel.recipients.join(", ")}</>}
              </p>
              <div>
                <h3 className="mb-1.5 text-xs font-semibold text-[var(--muted)]">영향받는 조문 · <Link href={workHref(sel.affected_work_id)}>{title(sel, "affected")}</Link></h3>
                <p className="whitespace-pre-wrap rounded-[10px] bg-[#f7f8fa] p-3 font-[family-name:var(--font-serif)] text-[15px] leading-relaxed">{sel.affected_text ?? sel.evidence ?? "-"}</p>
                {sel.evidence && <p className="mt-1 text-xs text-[var(--muted)]">근거 문구: <mark>{sel.evidence}</mark></p>}
              </div>
              <div>
                <h3 className="mb-1.5 text-xs font-semibold text-[var(--muted)]">상위 조문 신구 비교</h3>
                <div className="grid gap-2 md:grid-cols-2">
                  <div className="rounded-[10px] border border-[var(--line)] p-3"><p className="mb-1 text-xs font-semibold text-[var(--red)]">구</p><p className="whitespace-pre-wrap text-sm">{sel.cause_old ?? "(없음)"}</p></div>
                  <div className="rounded-[10px] border border-[var(--line)] p-3"><p className="mb-1 text-xs font-semibold text-[var(--green)]">신</p><p className="whitespace-pre-wrap text-sm">{sel.cause_new ?? "(삭제)"}</p></div>
                </div>
              </div>
              {sel.resolution_note && <p className="text-sm">처리 의견: {sel.resolution_note}</p>}
              {tab === "open" && <AlertActions id={sel.id} />}
            </section>
          )}
        </div>
      )}
    </main>
  );
}
