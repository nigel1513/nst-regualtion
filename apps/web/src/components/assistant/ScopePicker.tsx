"use client";
import { ChevronDown, Filter, Search, X } from "lucide-react";
import { useMemo, useState } from "react";
import { buttonClass } from "@/components/ui/button";
import { cn } from "@/components/ui/cn";
import { Checkbox } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { SegmentedControl } from "@/components/ui/segmented";
import { field, iconStroke } from "@/components/ui/styles";
import type { Scope } from "@/lib/chat";
import type { InstOption } from "@/lib/institution";

export function scopeLabel(scope: Scope, insts: InstOption[], workTitle?: string | null): string {
  if (scope.work_ids.length && workTitle) return workTitle;
  if (scope.mode === "all" || scope.institutions.length === 0) return "전체 기관";
  const first = insts.find((i) => i.code === scope.institutions[0])?.name ?? scope.institutions[0];
  return scope.institutions.length > 1 ? `${first} 외 ${scope.institutions.length - 1}곳` : first;
}

/** 범위 단추 → 팝오버: 전체 / 기관 선택(여럿, 찾기). 규정 하나로 좁힌 범위(이 규정에 묻기)는 지울 수 있다. */
export function ScopePicker({ scope, onChange, insts, workTitle }: {
  scope: Scope; onChange: (s: Scope) => void; insts: InstOption[]; workTitle?: string | null;
}) {
  const [q, setQ] = useState("");
  const list = useMemo(() => insts.filter((i) => i.works > 0 && (!q.trim() || i.name.includes(q.trim()) || i.code.toLowerCase().includes(q.trim().toLowerCase()))), [insts, q]);
  const toggle = (code: string) => {
    const has = scope.institutions.includes(code);
    const next = has ? scope.institutions.filter((c) => c !== code) : [...scope.institutions, code];
    onChange({ ...scope, mode: next.length ? "institutions" : "all", institutions: next, work_ids: [] });
  };
  return (
    <Popover>
      <PopoverTrigger className={buttonClass("secondary", "sm", "max-w-[60vw]")}>
        <Filter aria-hidden="true" strokeWidth={iconStroke} />
        <span className="truncate">범위: {scopeLabel(scope, insts, workTitle)}</span>
        <ChevronDown aria-hidden="true" strokeWidth={iconStroke} />
      </PopoverTrigger>
      <PopoverContent side="top" className="w-[320px] p-3">
        <SegmentedControl aria-label="질문 범위" className="flex w-full [&>*]:flex-1 [&>*]:justify-center" value={scope.mode === "all" && !scope.work_ids.length ? "all" : "institutions"}
          onValueChange={(v) => onChange(v === "all" ? { mode: "all", institutions: [], work_ids: [] } : { ...scope, mode: "institutions" })}
          items={[{ value: "all", label: "전체 기관" }, { value: "institutions", label: "기관 선택" }]} />
        {scope.work_ids.length && workTitle ? (
          <div className="mt-3 flex items-center gap-2 rounded-sm bg-bg-subtle px-2.5 py-2 text-small">
            <span className="min-w-0 flex-1 truncate">이 규정만: <span className="font-medium">{workTitle}</span></span>
            <button type="button" aria-label="규정 범위 풀기" onClick={() => onChange({ ...scope, work_ids: [] })}
              className="inline-flex size-6 cursor-pointer items-center justify-center rounded-sm text-fg-muted hover:bg-bg-hover hover:text-fg">
              <X aria-hidden="true" className="size-3.5" strokeWidth={iconStroke} />
            </button>
          </div>
        ) : null}
        {scope.mode === "institutions" ? (
          <>
            <label className="relative mt-3 block">
              <span className="sr-only">기관 찾기</span>
              <Search aria-hidden="true" className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-fg-subtle" strokeWidth={iconStroke} />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="기관 이름" className={cn(field, "pl-8")} />
            </label>
            <ul className="mt-2 max-h-60 overflow-y-auto" aria-label="기관">
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
        <p className="mt-2 text-caption font-normal text-fg-muted">질문에 기관 이름이 있으면 그 기관으로 좁힙니다. 기관을 고르면 고른 쪽이 먼저입니다.</p>
      </PopoverContent>
    </Popover>
  );
}
