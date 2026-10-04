"use client";
import { ArrowUp, History, Plus, Square } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Crumbs } from "@/components/shell/Breadcrumbs";
import { Button } from "@/components/ui/button";
import { cn } from "@/components/ui/cn";
import { iconStroke } from "@/components/ui/styles";
import { ChatHttpError, type ChatEvent, requestScope, type Scope, streamChat, type TopicOption } from "@/lib/chat";
import { setLocalValue, useIsClient, useLocalValue } from "@/lib/hooks";
import type { InstOption } from "@/lib/institution";
import { CitationRail } from "./CitationRail";
import { ScopePicker, scopeLabel } from "./ScopePicker";
import { TurnView } from "./TurnView";
import { CHATS_KEY, history, newTurn, type SavedChat, type Turn } from "./types";

const EXAMPLES = ["천문연 여비규정 27조", "출장 다녀온 지 10일 지났는데 증빙 안 냈어요", "출장 증빙은 며칠 안에 내야 하나요? 다른 기관도", "연구장비 구매 절차"];

/** scopeText: 규정·주제로 좁힌 범위면 그 한 줄 (차례 머리에 그대로 보인다). */
function apply(t: Turn, e: ChatEvent, insts: InstOption[], scopeText: string | null = null): Turn {
  switch (e.event) {
    case "status": {
      const d = e.data;
      const names = d.institutions?.map((i) => i.name).filter(Boolean) ?? [];
      const scopeNote = !d.scope_mode ? t.scopeNote : scopeText ? `범위 · ${scopeText}`
        : `범위 · ${d.scope_mode === "all" || names.length === 0 ? `전체 기관 ${insts.filter((i) => i.works > 0).length}곳` : names.join(", ")}`;
      return { ...t, stage: d.stage, stageLabel: d.label, intent: d.intent ?? t.intent, scopeNote };
    }
    case "results": return { ...t, cards: e.data.cards };
    case "answer_delta": return { ...t, delta: t.delta + e.data.text };
    case "answer": return { ...t, answer: e.data };
    case "table": return { ...t, table: e.data };
    case "citations": return { ...t, citations: e.data.items };
    case "followups": return { ...t, followups: e.data.items };
    case "done": return { ...t, done: e.data, ...(e.data.status === "error" ? { error: { status: 500, message: e.data.note ?? "" } } : {}) };
  }
}

function loadChats(raw: string | null): SavedChat[] {
  try {
    const v = JSON.parse(raw ?? "[]");
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}

/**
 * 규정 도우미 (서비스 UI 개편 §5): 가운데 대화 | 오른쪽 레일 320px(근거 N · 질문 범위 · 최근 대화).
 * POST /api/v1/chat SSE를 읽어 차례(turn)를 채운다. Esc나 멈춤 단추로 스트림을 끊는다.
 */
export function Assistant({ insts, topics = [], initialQ, initialScope }: {
  insts: InstOption[]; topics?: TopicOption[]; initialQ: string; initialScope: Scope;
}) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [scope, setScope] = useState<Scope>(initialScope);
  const [text, setText] = useState("");
  const [cid, setCid] = useState<string | undefined>(undefined);
  const [active, setActive] = useState<{ turn: string; n: number } | null>(null);
  const ctl = useRef<AbortController | null>(null);
  const sentInitial = useRef(false);
  const input = useRef<HTMLTextAreaElement>(null);
  const client = useIsClient();
  const chats = loadChats(useLocalValue(CHATS_KEY));
  const busy = turns.some((t) => !t.done && !t.error && !t.stopped);

  const save = useCallback((id: string, all: Turn[], sc: Scope) => {
    const done = all.filter((t) => t.done || t.error);
    if (!done.length) return;
    const rest = loadChats(window.localStorage.getItem(CHATS_KEY)).filter((c) => c.id !== id);
    setLocalValue(CHATS_KEY, JSON.stringify([{ id, title: done[0].question.slice(0, 80), at: Date.now(), turns: done, scope: sc }, ...rest].slice(0, 8)));
  }, []);

  const send = useCallback(async (question: string, prior?: Turn[]) => {
    const q = question.trim();
    if (q.length < 2) return;
    const base = prior ?? turns;
    const turn = newTurn(q);
    setTurns([...base, turn]);
    setText("");
    const ac = new AbortController();
    ctl.current = ac;
    let conv = cid;
    const patch = (fn: (t: Turn) => Turn) => setTurns((all) => all.map((x) => (x.id === turn.id ? fn(x) : x)));
    let latest: Turn = turn;
    const scopeText = scope.work_ids.length || scope.topic ? scopeLabel(scope, insts, topics) : null;
    try {
      await streamChat(
        { messages: [...history(base), { role: "user", content: q }], scope: requestScope(scope), ...(conv ? { conversation_id: conv } : {}) },
        (e) => {
          if (e.event === "status" && e.data.conversation_id) { conv = e.data.conversation_id; setCid(conv); }
          latest = apply(latest, e, insts, scopeText);
          patch((t) => apply(t, e, insts, scopeText));
        },
        ac.signal,
      );
      if (!latest.done) patch((t) => ({ ...t, done: t.done ?? { conversation_id: conv ?? "", qa_id: null, intent: t.intent ?? null, status: t.answer ? "answered" : "evidence_only", note: null, first_results_ms: null, latency_ms: 0 } }));
    } catch (err) {
      if (ac.signal.aborted) patch((t) => ({ ...t, stopped: true }));
      else patch((t) => ({ ...t, error: { status: err instanceof ChatHttpError ? err.status : 0, message: err instanceof ChatHttpError ? err.message : "" } }));
    } finally {
      ctl.current = null;
    }
  }, [turns, scope, cid, insts, topics]);

  // 한 차례가 끝나면 이 브라우저의 최근 대화에 남긴다
  useEffect(() => {
    if (cid && !busy && turns.length) save(cid, turns, scope);
  }, [busy, cid, turns, scope, save]);

  // ⌘K·/search·/qa에서 넘어온 질문은 바로 보낸다 (한 번만)
  useEffect(() => {
    if (initialQ && !sentInitial.current) {
      sentInitial.current = true;
      void send(initialQ, []);
    }
  }, [initialQ, send]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && ctl.current) ctl.current.abort(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const railTurn = useMemo(() => {
    if (active) return turns.find((t) => t.id === active.turn);
    return [...turns].reverse().find((t) => t.citations.length) ?? turns[turns.length - 1];
  }, [turns, active]);

  const workTitle = scope.work_ids.length === 1 ? scope.works?.find((w) => w.id === scope.work_ids[0])?.title ?? null : null;
  const reset = () => { ctl.current?.abort(); setTurns([]); setCid(undefined); setActive(null); input.current?.focus(); };
  const restore = (c: SavedChat) => { ctl.current?.abort(); setTurns(c.turns); setCid(c.id); setActive(null); };
  const retry = () => {
    const last = turns[turns.length - 1];
    if (last) void send(last.question, turns.slice(0, -1));
  };

  return (
    <div className="grid max-w-[1280px] grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_320px]">
      {turns[0] ? <Crumbs items={[{ label: turns[0].question.length > 24 ? `${turns[0].question.slice(0, 24)}…` : turns[0].question }]} /> : null}
      <section aria-label="대화" className="flex min-h-[calc(100dvh-160px)] min-w-0 max-w-[820px] flex-col">
        {turns.length === 0 ? (
          <div className="mb-8">
            <h1 className="text-display text-fg">규정 도우미</h1>
            <p className="mt-1.5 text-body text-fg-muted">조문을 찾거나 규정에 대해 물어보세요. 답의 근거는 모두 원문 그대로 인용합니다.</p>
            <div className="mt-5 flex flex-col items-start gap-1.5">
              {EXAMPLES.map((x) => (
                <button key={x} type="button" onClick={() => void send(x)}
                  className="press cursor-pointer rounded-sm px-2 py-1 text-left text-body text-accent-fg hover:bg-bg-hover">{x}</button>
              ))}
            </div>
          </div>
        ) : (
          <>
            <h1 className="sr-only">규정 도우미</h1>
            <div className="flex flex-col gap-8 pb-6">
              {turns.map((t, i) => (
                <TurnView key={t.id} t={t} last={i === turns.length - 1} busy={busy} onAsk={(q) => void send(q)} onRetry={retry}
                  onCite={(turn, n) => setActive({ turn, n })} />
              ))}
            </div>
          </>
        )}
        <div data-composer="" className="sticky bottom-0 mt-auto bg-bg pb-4 pt-2">
          <form onSubmit={(e) => { e.preventDefault(); if (!busy) void send(text); }}
            className="rounded-md border border-border-strong bg-bg-panel px-3 pb-2.5 pt-2 focus-within:border-focus focus-within:ring-3 focus-within:ring-focus-ring">
            <label htmlFor="ask" className="sr-only">질문</label>
            <textarea id="ask" ref={input} value={text} onChange={(e) => setText(e.target.value)} rows={2} maxLength={2000}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); if (!busy) void send(text); }
              }}
              placeholder={turns.length ? "이어서 물어보세요" : workTitle ? `${workTitle}에 대해 물어보세요` : "예: 출장 증빙은 며칠 안에 내야 하나요?"}
              className="block max-h-48 min-h-11 w-full resize-none bg-transparent text-long text-fg outline-none placeholder:text-fg-subtle" />
            <div className="mt-1 flex items-center justify-between gap-2">
              <ScopePicker scope={scope} onChange={setScope} insts={insts} topics={topics} />
              {busy ? (
                <Button size="sm" onClick={() => ctl.current?.abort()} aria-label="멈추기 (Esc)">
                  <Square aria-hidden="true" strokeWidth={iconStroke} className="!size-3.5" />멈추기
                </Button>
              ) : (
                <Button type="submit" variant="primary" size="icon-sm" aria-label="보내기" disabled={text.trim().length < 2}>
                  <ArrowUp aria-hidden="true" strokeWidth={2} />
                </Button>
              )}
            </div>
          </form>
          <p className="mt-1.5 text-caption font-normal text-fg-muted">개인정보는 입력하지 마세요. 답은 법적 판단이 아닙니다.</p>
        </div>
      </section>

      <aside className="flex flex-col gap-8 self-start lg:sticky lg:top-[72px] lg:max-h-[calc(100dvh-96px)] lg:overflow-y-auto">
        <CitationRail items={railTurn?.citations ?? []} active={active && railTurn && active.turn === railTurn.id ? active.n : null} />
        <section aria-labelledby="scope-h">
          <h2 id="scope-h" className="mb-1.5 text-caption text-fg-muted">질문 범위</h2>
          <p className="text-small text-fg">{scopeLabel(scope, insts, topics)}</p>
          <p className="mt-1 text-caption font-normal text-fg-muted">입력 상자 아래 범위 단추로 바꿉니다.</p>
        </section>
        <section aria-labelledby="recent-h" className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <h2 id="recent-h" className="text-caption text-fg-muted">최근 대화</h2>
            {turns.length ? (
              <Button variant="ghost" size="sm" onClick={reset}><Plus aria-hidden="true" strokeWidth={iconStroke} />새 대화</Button>
            ) : null}
          </div>
          {client && chats.length ? (
            <details className="group">
              <summary className="flex cursor-pointer list-none items-center gap-1.5 text-small text-fg-muted hover:text-fg">
                <History aria-hidden="true" className="size-4" strokeWidth={iconStroke} />{chats.length}개 펼치기
              </summary>
              <ul className="mt-1.5 flex flex-col">
                {chats.map((c) => (
                  <li key={c.id}>
                    <button type="button" onClick={() => restore(c)}
                      className={cn("w-full cursor-pointer truncate rounded-sm px-2 py-1.5 text-left text-small hover:bg-bg-hover", c.id === cid ? "bg-bg-active text-fg" : "text-fg")}>
                      {c.title}
                    </button>
                  </li>
                ))}
              </ul>
            </details>
          ) : <p className="text-small text-fg-muted">이 브라우저에 남은 대화가 없습니다.</p>}
        </section>
      </aside>
    </div>
  );
}
