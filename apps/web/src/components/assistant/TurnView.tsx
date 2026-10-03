"use client";
import { Columns3, RotateCcw } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Badge, type Tone } from "@/components/ui/badge";
import { Button, buttonClass } from "@/components/ui/button";
import { cn } from "@/components/ui/cn";
import { InstitutionMark } from "@/components/ui/institution-mark";
import { iconStroke } from "@/components/ui/styles";
import { Table, TBody, Td, Th, THead, Tr } from "@/components/ui/table";
import { CardList } from "./Cards";
import type { Turn } from "./types";

const VERDICT: Record<string, Tone> = { 미충족: "danger", 조건부: "warning", 충족: "success", 판단불가: "neutral" };

function Sup({ n, onCite }: { n: number; onCite: (n: number) => void }) {
  return (
    <sup className="ml-px">
      <button type="button" onClick={() => onCite(n)} aria-label={`근거 ${n}`}
        className="num cursor-pointer rounded-xs px-0.5 text-micro font-semibold text-accent-fg hover:bg-accent-soft">{n}</button>
    </sup>
  );
}

function errorText(t: Turn): string {
  const s = t.error?.status ?? 0;
  if (s === 429) return "지금 질문이 몰려 있습니다. 잠시 뒤 다시 보내 주세요.";
  if (s === 503) return "검색 색인을 준비하고 있습니다. 잠시 뒤 다시 시도해 주세요.";
  return t.error?.message || "답을 받지 못했습니다. 다시 보내 주세요.";
}

/** 한 차례: 사용자 말풍선(--bg-hover 면) · 진행 줄 · 답(면 없이 본문, 문장마다 근거 번호) · 기관별 표 · 조문 카드 · 후속 질문. */
export function TurnView({ t, last, busy, onCite, onAsk, onRetry }: {
  t: Turn; last: boolean; busy: boolean; onCite: (turn: string, n: number) => void; onAsk: (q: string) => void; onRetry: () => void;
}) {
  const [allCards, setAllCards] = useState(false);
  const running = !t.done && !t.error && !t.stopped;
  const cite = (n: number) => onCite(t.id, n);
  const answered = !!t.answer || !!t.table;
  const lookup = t.intent === "lookup" || (!answered && t.done);
  return (
    <article className="flex flex-col gap-4" aria-label={`질문: ${t.question}`} data-state={running ? "running" : "settled"}>
      <div className="max-w-[80%] self-end whitespace-pre-wrap rounded-md bg-bg-hover px-3.5 py-2.5 text-long text-fg">{t.question}</div>
      <div className="flex min-w-0 flex-col gap-4">
        <p className="text-caption text-fg-muted" aria-live="polite">
          {running ? <span>{t.stageLabel ?? "질문을 보내는 중"}…</span>
            : t.error ? null
            : t.stopped ? "멈췄습니다"
            : <>{t.scopeNote ? `${t.scopeNote} · ` : ""}조문 <span className="num">{t.cards.length}</span>개 확인{t.done?.latency_ms ? <> · <span className="num">{(t.done.latency_ms / 1000).toFixed(1)}</span>초</> : null}</>}
        </p>

        {t.error ? (
          <div className="flex flex-wrap items-center gap-3 rounded-md border border-border bg-bg-subtle px-4 py-3 text-small text-fg">
            {errorText(t)}
            {last ? <Button size="sm" onClick={onRetry}><RotateCcw aria-hidden="true" strokeWidth={iconStroke} />다시 보내기</Button> : null}
          </div>
        ) : null}

        {t.answer ? (
          <div className="flex flex-col gap-3">
            {t.answer.conclusion ? <div><Badge tone={VERDICT[t.answer.conclusion] ?? "neutral"} className="h-6 px-2 text-small font-semibold">{t.answer.conclusion}</Badge></div> : null}
            <p className="text-long text-fg">
              {t.answer.sentences.length
                ? t.answer.sentences.map((s, i) => <span key={i}>{i > 0 ? " " : ""}{s.text}{s.cites.map((n) => <Sup key={n} n={n} onCite={cite} />)}</span>)
                : t.answer.explanation}
            </p>
            {t.answer.checks.length ? (
              <div className="text-small">
                <p className="mb-1 font-semibold text-fg">확인할 점</p>
                <ul className="list-disc pl-5 text-fg">{t.answer.checks.map((c, i) => <li key={i}>{c}</li>)}</ul>
              </div>
            ) : null}
            <p className="text-caption font-normal text-fg-muted">
              {t.answer.contact ? `문의: ${t.answer.contact} · ` : ""}법적 판단이 아니며 소관부서 확인이 필요합니다.
            </p>
          </div>
        ) : t.delta && running ? <p className="text-long text-fg-muted">{t.delta}</p> : null}

        {t.table ? (
          <div className="flex flex-col gap-2">
            <p className="text-small text-fg"><span className="font-semibold">{t.table.item}</span>
              <span className="text-fg-muted"> · 기관 {t.table.rows.length}곳{t.table.source === "extracted" ? " · 조문에서 뽑은 값" : ""}</span></p>
            <Table caption={`${t.table.item} 기관별 비교`}>
              <THead><Tr><Th>기관</Th><Th>{t.table.unit ? `값 (${t.table.unit})` : "값"}</Th><Th>근거</Th></Tr></THead>
              <TBody>
                {t.table.rows.map((r, i) => (
                  <Tr key={`${r.institution.code}-${i}`}>
                    <Td className="whitespace-nowrap"><span className="inline-flex items-center gap-1.5"><InstitutionMark code={r.institution.code} />{r.institution.name}</span></Td>
                    <Td className={cn("num", r.institution.code === t.table?.focus && "font-semibold")}>
                      {r.absent || !r.value ? <span className="text-fg-muted">규정 없음</span> : r.value}
                    </Td>
                    <Td className="whitespace-nowrap">
                      {r.href ? <Link href={r.href}>{r.title ?? "원문"}</Link> : null}
                      {r.cite ? <Sup n={r.cite} onCite={cite} /> : null}
                    </Td>
                  </Tr>
                ))}
              </TBody>
            </Table>
          </div>
        ) : null}

        {t.cards.length > 0 && (lookup || !running) ? (
          <section aria-label="찾은 조문" className="flex flex-col gap-2">
            {answered ? <h3 className="text-caption text-fg-muted">찾은 조문 <span className="num">{t.cards.length}</span></h3> : null}
            <CardList cards={t.cards} limit={allCards || lookup ? undefined : 3} />
            {!allCards && !lookup && t.cards.length > 3 ? (
              <button type="button" onClick={() => setAllCards(true)} className="self-start text-small text-accent-fg hover:underline">
                조문 {t.cards.length - 3}개 더 보기
              </button>
            ) : null}
          </section>
        ) : null}

        {t.done?.status === "not_found" ? <p className="text-small text-fg-muted">{t.done.note ?? "맞는 조문을 찾지 못했습니다. 다른 말로 물어보세요."}</p> : null}

        {t.followups.length > 0 || t.table ? (
          <div className="flex flex-wrap gap-1.5">
            {t.table ? (
              <Link href={`/compare?${new URLSearchParams({ ...(t.table.topic ? { topic: t.table.topic } : {}), ...(t.table.item_id ? { item: t.table.item_id } : {}) })}`}
                className={buttonClass("secondary", "sm")}><Columns3 aria-hidden="true" strokeWidth={iconStroke} />기관 비교표로 보기</Link>
            ) : null}
            {t.followups.map((f) => <Button key={f} size="sm" disabled={busy} onClick={() => onAsk(f)}>{f}</Button>)}
          </div>
        ) : null}
      </div>
    </article>
  );
}
