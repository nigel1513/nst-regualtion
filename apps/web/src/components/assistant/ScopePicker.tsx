"use client";
import { ChevronDown, Filter, Search, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { buttonClass } from "@/components/ui/button";
import { cn } from "@/components/ui/cn";
import { Checkbox } from "@/components/ui/input";
import { InstitutionMark } from "@/components/ui/institution-mark";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { SegmentedControl } from "@/components/ui/segmented";
import { SelectMenu } from "@/components/ui/select";
import { field, iconStroke } from "@/components/ui/styles";
import type { Scope, ScopeWork, TopicOption } from "@/lib/chat";
import type { InstOption } from "@/lib/institution";

const MAX_WORKS = 10;
const NO_TOPIC = "none";
type Suggest = { title: string; work_id: string; institution: string | null; institution_name: string | null };

/** 범위 한 줄: "한국천문연구원 · 콜로키움운영기준", "한국천문연구원 외 1곳 · 여비·출장", "전체 기관". */
export function scopeLabel(scope: Scope, insts: InstOption[], topics: TopicOption[] = []): string {
  const name = (c: string) => insts.find((i) => i.code === c)?.name ?? c;
  const several = (first: string, n: number, unit: string) => (n > 1 ? `${first} 외 ${n - 1}${unit}` : first);
  if (scope.work_ids.length) {
    const works = scope.work_ids.map((id) => scope.works?.find((w) => w.id === id) ?? { id, title: id.split("/").pop() ?? id, institution: null });
    const codes = [...new Set(works.map((w) => w.institution).filter((c): c is string => !!c && insts.some((i) => i.code === c)))];   // 법령(LAW)은 기관이 아니다
    return [codes.length ? several(name(codes[0]), codes.length, "곳") : null, several(works[0].title, works.length, "개")].filter(Boolean).join(" · ");
  }
  const inst = scope.mode === "all" || scope.institutions.length === 0 ? "전체 기관" : several(name(scope.institutions[0]), scope.institutions.length, "곳");
  const topic = scope.topic ? topics.find((t) => t.id === scope.topic)?.label ?? scope.topic : null;
  return [inst, topic].filter(Boolean).join(" · ");
}

/** 규정명 자동완성 (/api/v1/search/suggest): 150ms 기다렸다가 부르고, 늦게 온 옛 응답은 버린다. */
function useSuggest(q: string, institution: string | null) {
  const [state, setState] = useState<{ key: string; rows: Suggest[] }>({ key: "", rows: [] });
  const key = `${q.trim()}|${institution ?? ""}`;
  useEffect(() => {
    const t = q.trim();
    if (!t) return;
    const ctl = new AbortController();
    const timer = window.setTimeout(async () => {
      try {
        const r = await fetch(`/api/v1/search/suggest?${new URLSearchParams({ q: t, size: "6", ...(institution ? { institution } : {}) })}`, { signal: ctl.signal });
        const rows = r.ok ? ((await r.json()) as Suggest[]) : [];
        if (!ctl.signal.aborted) setState({ key: `${t}|${institution ?? ""}`, rows });
      } catch { /* 끊김·취소 */ }
    }, 150);
    return () => { ctl.abort(); window.clearTimeout(timer); };
  }, [q, institution]);
  return state.key === key ? state.rows : [];
}

function WorkChip({ w, onRemove }: { w: ScopeWork; onRemove: () => void }) {
  return (
    <li className="inline-flex h-7 max-w-full items-center gap-1.5 rounded-sm border border-border bg-bg-subtle pl-1 pr-0.5 text-small text-fg">
      <InstitutionMark code={w.institution} />
      <span className="min-w-0 truncate">{w.title}</span>
      <button type="button" aria-label={`${w.title} 범위에서 빼기`} onClick={onRemove}
        className="inline-flex size-6 shrink-0 cursor-pointer items-center justify-center rounded-xs text-fg-muted hover:bg-bg-hover hover:text-fg">
        <X aria-hidden="true" className="size-3.5" strokeWidth={iconStroke} />
      </button>
    </li>
  );
}

/**
 * 범위 단추 → 팝오버: 기관(전체 / 기관 선택), 규정(이름으로 찾아 여럿, 칩), 주제. 규정을 고르면 그 규정 안에서만 찾고
 * 기관도 그 규정의 기관으로 정해진다 (주제는 쓰지 않는다). "이 규정에 묻기"로 온 범위도 칩으로 보이고 뺄 수 있다.
 */
export function ScopePicker({ scope, onChange, insts, topics = [] }: {
  scope: Scope; onChange: (s: Scope) => void; insts: InstOption[]; topics?: TopicOption[];
}) {
  const [q, setQ] = useState("");
  const [rq, setRq] = useState("");
  const list = useMemo(() => insts.filter((i) => i.works > 0 && (!q.trim() || i.name.includes(q.trim()) || i.code.toLowerCase().includes(q.trim().toLowerCase()))), [insts, q]);
  const works = scope.work_ids.map((id) => scope.works?.find((w) => w.id === id) ?? { id, title: id.split("/").pop() ?? id, institution: null });
  const oneInst = scope.mode === "institutions" && scope.institutions.length === 1 ? scope.institutions[0] : null;
  const found = useSuggest(rq, oneInst).filter((r) => !scope.work_ids.includes(r.work_id));
  const toggle = (code: string) => {
    const has = scope.institutions.includes(code);
    const next = has ? scope.institutions.filter((c) => c !== code) : [...scope.institutions, code];
    onChange({ ...scope, mode: next.length ? "institutions" : "all", institutions: next });
  };
  const setWorks = (ws: ScopeWork[]) => onChange({ ...scope, work_ids: ws.map((w) => w.id), works: ws });
  const add = (r: Suggest) => {
    setWorks([...works, { id: r.work_id, title: r.title, institution: r.institution }].slice(0, MAX_WORKS));
    setRq("");
  };
  return (
    <Popover>
      <PopoverTrigger className={buttonClass("secondary", "sm", "max-w-[60vw]")}>
        <Filter aria-hidden="true" strokeWidth={iconStroke} />
        <span className="truncate">범위: {scopeLabel(scope, insts, topics)}</span>
        <ChevronDown aria-hidden="true" strokeWidth={iconStroke} />
      </PopoverTrigger>
      <PopoverContent side="top" className="flex max-h-[min(var(--available-height),640px)] w-[360px] flex-col gap-4 overflow-y-auto p-3">
        <section aria-labelledby="scope-inst-h">
          <h3 id="scope-inst-h" className="mb-1.5 text-caption text-fg-muted">기관</h3>
          <SegmentedControl aria-label="기관 범위" className="flex w-full [&>*]:flex-1 [&>*]:justify-center" value={scope.mode === "all" ? "all" : "institutions"}
            onValueChange={(v) => onChange(v === "all" ? { ...scope, mode: "all", institutions: [], work_ids: [], works: [] } : { ...scope, mode: "institutions" })}
            items={[{ value: "all", label: "전체 기관" }, { value: "institutions", label: "기관 선택" }]} />
          {scope.mode === "institutions" ? (
            <>
              <label className="relative mt-2 block">
                <span className="sr-only">기관 찾기</span>
                <Search aria-hidden="true" className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-fg-subtle" strokeWidth={iconStroke} />
                <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="기관 이름" className={cn(field, "pl-8")} />
              </label>
              <ul className="mt-1.5 max-h-40 overflow-y-auto" aria-label="기관">
                {list.map((i) => (
                  <li key={i.code}>
                    <label className="flex h-8 cursor-pointer items-center gap-2 rounded-sm px-1.5 text-small hover:bg-bg-hover">
                      <Checkbox checked={scope.institutions.includes(i.code)} onChange={() => toggle(i.code)} />
                      <span className="min-w-0 flex-1 truncate">{i.name}</span>
                    </label>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
        </section>

        <section aria-labelledby="scope-work-h">
          <h3 id="scope-work-h" className="mb-1.5 text-caption text-fg-muted">규정</h3>
          {works.length ? (
            <ul className="mb-2 flex flex-wrap gap-1.5" aria-label="고른 규정">
              {works.map((w) => <WorkChip key={w.id} w={w} onRemove={() => setWorks(works.filter((x) => x.id !== w.id))} />)}
            </ul>
          ) : null}
          {works.length < MAX_WORKS ? (
            <div className="relative">
              <label className="relative block">
                <span className="sr-only">규정 이름으로 찾기</span>
                <Search aria-hidden="true" className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-fg-subtle" strokeWidth={iconStroke} />
                <input value={rq} onChange={(e) => setRq(e.target.value)} placeholder={oneInst ? "이 기관 규정 이름" : "규정 이름"} className={cn(field, "pl-8")}
                  onKeyDown={(e) => { if (e.key === "Enter" && found[0]) { e.preventDefault(); add(found[0]); } }} />
              </label>
              {rq.trim() && found.length ? (
                <ul className="mt-1 max-h-48 overflow-y-auto" aria-label="찾은 규정">
                  {found.map((r) => (
                    <li key={r.work_id}>
                      <button type="button" onClick={() => add(r)}
                        className="flex h-8 w-full cursor-pointer items-center gap-2 rounded-sm px-1.5 text-left text-small text-fg hover:bg-bg-hover">
                        <InstitutionMark code={r.institution} />
                        <span className="min-w-0 flex-1 truncate">{r.title}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}
        </section>

        <section aria-labelledby="scope-topic-h">
          <h3 id="scope-topic-h" className="mb-1.5 text-caption text-fg-muted">주제</h3>
          {works.length ? (
            <p className="text-small text-fg-muted">규정을 고르면 그 규정 안에서만 찾습니다.</p>
          ) : (
            <SelectMenu aria-label="주제" size="sm" value={scope.topic ?? NO_TOPIC}
              onValueChange={(v) => onChange({ ...scope, topic: v && v !== NO_TOPIC ? v : undefined })}
              options={[{ value: NO_TOPIC, label: "주제 없음" }, ...topics.filter((t) => t.works > 0).map((t) => ({ value: t.id, label: t.label }))]} />
          )}
        </section>
        <p className="text-caption font-normal text-fg-muted">질문에 기관 이름이 있으면 그 기관으로 좁힙니다. 고른 기관·규정이 먼저입니다.</p>
      </PopoverContent>
    </Popover>
  );
}
