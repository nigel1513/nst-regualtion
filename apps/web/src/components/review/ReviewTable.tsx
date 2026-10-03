"use client";
import { ChevronDown, ChevronRight, ExternalLink, FileText, Link2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Fragment, useState } from "react";
import { Badge, type Tone } from "@/components/ui/badge";
import { Button, buttonClass } from "@/components/ui/button";
import { cn } from "@/components/ui/cn";
import { Checkbox, Input } from "@/components/ui/input";
import { InstitutionMark } from "@/components/ui/institution-mark";
import { field, iconStroke } from "@/components/ui/styles";
import { fmtDate } from "@/lib/format";
import { NameDialog } from "./MyName";
import { useReviewer } from "./reviewer";
import { REF_KINDS, type ReviewTaskItem } from "./types";

function statusOf(t: ReviewTaskItem): { label: string; tone: Tone } {
  if (t.status === "OPEN") return t.assignee ? { label: "진행 중", tone: "accent" } : { label: "열림", tone: "warning" };
  if (t.status === "HOLD") return { label: "보류", tone: "neutral" };
  if (t.status === "RESOLVED") return { label: "해결", tone: "success" };
  return { label: "문제 없음", tone: "neutral" };
}

/** 처리 기록(by)·"나에게"에 쓰는 이름: 방금 적은 이름도 잡도록 부를 때 읽는다. */
function savedName(): string | null {
  try {
    return window.localStorage.getItem("nst-reg-reviewer")?.trim() || null;
  } catch {
    return null;
  }
}

async function post(path: string, body: unknown): Promise<string | null> {
  try {
    const r = await fetch(`/api/v1/review-tasks/${path}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
    if (r.ok) return null;
    const d = (await r.json().catch(() => ({}))) as { detail?: unknown };
    return typeof d.detail === "string" ? d.detail : r.status === 422 ? "입력을 확인해 주세요" : "처리하지 못했습니다";
  } catch {
    return "서버에 연결하지 못했습니다";
  }
}

function Excerpt({ e }: { e: NonNullable<ReviewTaskItem["excerpt"]> }) {
  if (!e.highlight) return <>{e.text}</>;
  const [s, t] = e.highlight;
  return <>{e.text.slice(0, s)}<mark className="rounded-xs bg-mark text-inherit">{e.text.slice(s, t)}</mark>{e.text.slice(t)}</>;
}

type Mode = null | "link" | "resolve" | "dismiss" | "hold" | "reopen";

/** 펼친 행: 원문 발췌 · 주무부처 · 링크 · 처리(연결 지정 / 처리 완료 / 문제 없음 / 보류 / 다시 열기). */
function Detail({ t, needName }: { t: ReviewTaskItem; needName: (then: () => void) => void }) {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>(null);
  const [text, setText] = useState("");
  const [target, setTarget] = useState<{ work_id: string; title: string } | null>(null);
  const [article, setArticle] = useState("");
  const [hits, setHits] = useState<{ work_id: string; title: string; institution_name: string | null }[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const active = t.status === "OPEN" || t.status === "HOLD";
  const abolish = t.kind === "ABOLISHED";

  const run = (path: string, body: object) => needName(async () => {
    setBusy(true);
    setError(null);
    const err = await post(`${t.id}/${path}`, { ...body, ...(path === "assign" ? {} : { by: savedName() ?? undefined }) });
    setBusy(false);
    if (err) setError(err);
    else { setMode(null); setText(""); router.refresh(); }
  });
  const search = async (q: string) => {
    if (q.trim().length < 1) { setHits([]); return; }
    const r = await fetch(`/api/v1/search/suggest?${new URLSearchParams({ q, size: "6" })}`).catch(() => null);
    setHits(r?.ok ? await r.json() : []);
  };
  const art = article.trim().match(/^제?(\d+)조(?:의(\d+))?/);
  const path = art ? `a${art[1]}${art[2] ? `-${art[2]}` : ""}` : undefined;

  return (
    <div className="flex flex-col gap-3">
      {t.excerpt ? (
        <div>
          <p className="mb-1 text-caption text-fg-muted">{t.work_title} {t.location.label} 원문</p>
          <p className="text-small text-fg"><Excerpt e={t.excerpt} /></p>
        </div>
      ) : null}
      <dl className="flex flex-wrap gap-x-6 gap-y-1 text-small">
        <div className="flex gap-1.5"><dt className="text-fg-muted">종류</dt><dd>{t.kind_label}</dd></div>
        {t.version ? <div className="flex gap-1.5"><dt className="text-fg-muted">판본</dt><dd className="num">{fmtDate(t.version.effective_from)} 시행</dd></div> : null}
        {t.department ? <div className="flex gap-1.5"><dt className="text-fg-muted">주무부처</dt><dd>{t.department.name ?? t.department.code}</dd></div> : null}
        <div className="flex gap-1.5"><dt className="text-fg-muted">생성</dt><dd className="num">{fmtDate(t.created_at)}</dd></div>
        {t.decision && "action" in t.decision ? (
          <div className="flex gap-1.5"><dt className="text-fg-muted">마지막 처리</dt>
            <dd>{t.decision.by ?? "이름 없음"} · {fmtDate(t.decision.at)}{t.decision.reason ? ` · ${t.decision.reason}` : t.decision.note ? ` · ${t.decision.note}` : ""}</dd></div>
        ) : null}
      </dl>
      <div className="flex flex-wrap gap-2">
        {t.links.pdf ? <a href={t.links.pdf} target="_blank" rel="noreferrer" className={buttonClass("secondary", "sm")}><FileText aria-hidden="true" strokeWidth={iconStroke} />원문 PDF</a> : null}
        {t.links.source ? <Link href={t.links.source} className={buttonClass("secondary", "sm")}>원문 대조</Link> : null}
        {t.links.viewer ? <Link href={t.links.viewer} className={buttonClass("secondary", "sm")}><ExternalLink aria-hidden="true" strokeWidth={iconStroke} />규정 보기</Link> : null}
        <span className="mx-1 hidden w-px self-stretch bg-border sm:block" aria-hidden="true" />
        {active ? (
          <>
            {REF_KINDS.includes(t.kind) ? <Button size="sm" variant="primary" onClick={() => setMode("link")}><Link2 aria-hidden="true" strokeWidth={iconStroke} />연결 지정</Button> : null}
            <Button size="sm" variant={REF_KINDS.includes(t.kind) ? "secondary" : "primary"} onClick={() => setMode("resolve")}>{abolish ? "폐지 확정" : "처리 완료"}</Button>
            <Button size="sm" onClick={() => setMode("dismiss")}>{abolish ? "폐지 아님" : "문제 없음"}</Button>
            {t.status === "OPEN" ? <Button size="sm" onClick={() => setMode("hold")}>보류</Button> : null}
            {t.status === "HOLD" ? <Button size="sm" onClick={() => setMode("reopen")}>다시 열기</Button> : null}
          </>
        ) : t.decision && "action" in t.decision ? <Button size="sm" onClick={() => setMode("reopen")}>다시 열기</Button> : null}
      </div>

      {mode === "link" ? (
        <form className="flex flex-col gap-2 rounded-md border border-border bg-bg-panel p-3" onSubmit={(e) => {
          e.preventDefault();
          if (target) run("resolve", { decision: { target_work_id: target.work_id, ...(path ? { target_path: path } : {}) }, note: text.trim() || undefined });
        }}>
          <p className="text-small font-medium text-fg">이 인용을 이을 규정·법령</p>
          {target ? (
            <p className="flex items-center gap-2 text-small">{target.title}<button type="button" className="text-accent-fg hover:underline" onClick={() => setTarget(null)}>바꾸기</button></p>
          ) : (
            <>
              <input aria-label="규정 이름" placeholder="규정 이름" className={cn(field, "h-8")} onChange={(e) => void search(e.target.value)} />
              <ul className="flex flex-col">
                {hits.map((h) => (
                  <li key={h.work_id}>
                    <button type="button" onClick={() => setTarget({ work_id: h.work_id, title: h.title })}
                      className="flex w-full cursor-pointer justify-between rounded-sm px-2 py-1.5 text-left text-small hover:bg-bg-hover">
                      <span>{h.title}</span><span className="text-fg-muted">{h.institution_name ?? "법령"}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <Input aria-label="조 (선택)" placeholder="조 (예: 제12조, 선택)" value={article} onChange={(e) => setArticle(e.target.value)} className="h-8 w-44" />
            <Input aria-label="메모 (선택)" placeholder="메모 (선택)" value={text} onChange={(e) => setText(e.target.value)} className="h-8 min-w-40 flex-1" />
            <Button size="sm" variant="primary" type="submit" disabled={!target || busy}>연결하고 닫기</Button>
            <Button size="sm" variant="ghost" onClick={() => setMode(null)}>취소</Button>
          </div>
        </form>
      ) : mode ? (
        <form className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-bg-panel p-3" onSubmit={(e) => {
          e.preventDefault();
          const v = text.trim();
          if (mode === "dismiss") { if (v) run("dismiss", { reason: v }); return; }
          if (mode === "resolve") run("resolve", { decision: {}, note: v || undefined });
          if (mode === "hold") run("hold", { note: v || undefined });
          if (mode === "reopen") run("reopen", { note: v || undefined });
        }}>
          <Input autoFocus aria-label={mode === "dismiss" ? "사유" : "메모"} value={text} onChange={(e) => setText(e.target.value)} maxLength={1000}
            placeholder={mode === "dismiss" ? "사유 (필수): 예) 내부 기준이라 정상" : "메모 (선택)"} className="h-8 min-w-48 flex-1" />
          <Button size="sm" variant="primary" type="submit" disabled={busy || (mode === "dismiss" && !text.trim())}>
            {{ resolve: abolish ? "폐지 확정" : "처리 완료", dismiss: abolish ? "폐지 아님으로 닫기" : "문제 없음으로 닫기", hold: "보류", reopen: "다시 열기" }[mode]}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setMode(null)}>취소</Button>
        </form>
      ) : null}
      {error ? <p className="text-small text-danger" role="alert">{error}</p> : null}
    </div>
  );
}

/** 검수 표 (§6): 선택, 기관, 규정·위치, 문제, 해야 할 일, 담당, 상태 + 행 펼침. 선택하면 담당 일괄 지정 줄이 나온다. */
export function ReviewTable({ items }: { items: ReviewTaskItem[] }) {
  const router = useRouter();
  const [name] = useReviewer();
  const [open, setOpen] = useState<Set<number>>(new Set());
  const [sel, setSel] = useState<Set<number>>(new Set());
  const [askName, setAskName] = useState<null | (() => void)>(null);
  const [bulkMsg, setBulkMsg] = useState<string | null>(null);
  const needName = (then: () => void) => (name ? then() : setAskName(() => then));
  const flip = (s: Set<number>, id: number) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; };
  const all = items.length > 0 && items.every((t) => sel.has(t.id));
  const bulk = (assignee: string | null) => needName(async () => {
    const r = await fetch("/api/v1/review-tasks/bulk-assign", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ ids: [...sel], assignee: assignee === "me" ? savedName() : assignee }) }).catch(() => null);
    if (!r?.ok) { setBulkMsg("담당을 바꾸지 못했습니다"); return; }
    const d = (await r.json()) as { updated: number[]; skipped: number[] };
    setBulkMsg(`${d.updated.length}건 바꿈${d.skipped.length ? ` · 닫힌 작업 ${d.skipped.length}건은 건너뜀` : ""}`);
    setSel(new Set());
    router.refresh();
  });
  const assignOne = (t: ReviewTaskItem, who: string | null) => needName(async () => {
    const err = await post(`${t.id}/assign`, { assignee: who === "me" ? savedName() : who });
    if (err) setBulkMsg(err); else router.refresh();
  });

  return (
    <div className="flex flex-col gap-2">
      {sel.size > 0 ? (
        <div className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-bg-subtle px-3 py-2 text-small">
          <span className="num font-medium text-fg">{sel.size}건 선택</span>
          <Button size="sm" variant="primary" onClick={() => bulk("me")}>{name ? `${name}에게 담당 지정` : "나에게 담당 지정"}</Button>
          <Button size="sm" onClick={() => bulk(null)}>담당 해제</Button>
          <Button size="sm" variant="ghost" onClick={() => setSel(new Set())}>선택 해제</Button>
        </div>
      ) : null}
      {bulkMsg ? <p className="text-small text-fg-muted" role="status">{bulkMsg}</p> : null}
      <div role="region" aria-label="검수 작업" tabIndex={0} className="relative w-full overflow-x-auto rounded-md border border-border bg-bg-panel">
        <table className="w-full min-w-[960px] border-collapse text-small">
          <caption className="sr-only">검수 작업</caption>
          <thead className="bg-bg-subtle text-left">
            <tr>
              <th scope="col" className="h-9 w-10 border-b border-border px-3">
                <Checkbox aria-label="이 쪽 모두 선택" checked={all} onChange={() => setSel(all ? new Set() : new Set(items.map((t) => t.id)))} />
              </th>
              {["기관", "규정 · 위치", "문제", "해야 할 일", "담당", "상태"].map((h) => (
                <th key={h} scope="col" className="h-9 whitespace-nowrap border-b border-border px-3 text-caption text-fg-muted">{h}</th>
              ))}
              <th scope="col" className="h-9 w-10 border-b border-border"><span className="sr-only">펼치기</span></th>
            </tr>
          </thead>
          <tbody>
            {items.map((t) => {
              const st = statusOf(t);
              const isOpen = open.has(t.id);
              return (
                <Fragment key={t.id}>
                  <tr className={cn("border-b border-border-subtle align-top", isOpen ? "bg-bg-subtle" : "hover:bg-bg-hover", sel.has(t.id) && "bg-accent-soft")}>
                    <td className="px-3 py-2.5"><Checkbox aria-label={`${t.work_title ?? t.target} 선택`} checked={sel.has(t.id)} onChange={() => setSel((s) => flip(s, t.id))} /></td>
                    <td className="whitespace-nowrap px-3 py-2.5">
                      {t.institution ? <span className="inline-flex items-center gap-1.5"><InstitutionMark code={t.institution.code} />{t.institution.name}</span> : <span className="text-fg-muted">법령</span>}
                    </td>
                    <td className="min-w-[200px] px-3 py-2.5">
                      {t.links.viewer ? <Link href={t.links.viewer} className="font-semibold text-fg hover:text-fg">{t.work_title ?? "제목 없음"}</Link>
                        : <span className="font-semibold">{t.work_title ?? "제목 없음"}</span>}
                      <span className="text-fg"> {t.location.label}</span>
                      <div className="text-caption font-normal text-fg-muted">{t.kind_label}{t.version?.effective_from ? ` · ${fmtDate(t.version.effective_from)} 판본` : ""}</div>
                    </td>
                    <td className="min-w-[220px] px-3 py-2.5 text-fg">{t.problem}</td>
                    <td className="min-w-[220px] px-3 py-2.5 text-fg-muted">{t.todo}</td>
                    <td className="whitespace-nowrap px-3 py-2.5">
                      {t.assignee ? <span className="text-fg">{t.assignee}</span>
                        : (t.status === "OPEN" || t.status === "HOLD")
                          ? <button type="button" onClick={() => assignOne(t, "me")} className="cursor-pointer text-accent-fg hover:underline">내가 맡기</button>
                          : <span className="text-fg-muted">—</span>}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2.5"><Badge tone={st.tone}>{st.label}</Badge></td>
                    <td className="px-2 py-2">
                      <button type="button" aria-expanded={isOpen} aria-label={isOpen ? "접기" : "펼치기"} onClick={() => setOpen((s) => flip(s, t.id))}
                        className="press inline-flex size-7 cursor-pointer items-center justify-center rounded-sm text-fg-muted hover:bg-bg-active hover:text-fg">
                        {isOpen ? <ChevronDown aria-hidden="true" className="size-4" strokeWidth={iconStroke} /> : <ChevronRight aria-hidden="true" className="size-4" strokeWidth={iconStroke} />}
                      </button>
                    </td>
                  </tr>
                  {isOpen ? (
                    <tr className="border-b border-border-subtle bg-bg-subtle">
                      <td />
                      <td colSpan={7} className="px-3 pb-4 pt-1"><Detail t={t} needName={needName} /></td>
                    </tr>
                  ) : null}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      <NameDialog open={!!askName} onOpenChange={(o) => { if (!o) setAskName(null); }} onSaved={() => { const f = askName; setAskName(null); setTimeout(() => f?.(), 0); }} />
    </div>
  );
}
