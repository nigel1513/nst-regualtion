"use client";
import { Search, SlidersHorizontal } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { cn } from "@/components/ui/cn";
import { Checkbox } from "@/components/ui/input";
import { field, iconStroke } from "@/components/ui/styles";
import type { FacetItem } from "@/lib/api";
import { regHref, type RegQuery } from "./query";

function Group({ title, items, checked, onToggle, extra }: {
  title: string; items: { value: string; label: string; count: number; mark?: string }[]; checked: (v: string) => boolean;
  onToggle: (v: string) => void; extra?: React.ReactNode;
}) {
  if (items.length === 0) return null;
  return (
    <fieldset className="mt-5">
      <legend className="mb-1.5 text-caption text-fg-muted">{title}</legend>
      {extra}
      {items.map((it) => (
        <label key={it.value} className="flex min-h-7 cursor-pointer items-center gap-2 text-small text-fg">
          <Checkbox checked={checked(it.value)} onChange={() => onToggle(it.value)} />
          <span className="min-w-0 flex-1 truncate">{it.label}{it.mark ? <span className="text-fg-muted"> {it.mark}</span> : null}</span>
          <span className="num text-caption text-fg-muted">{it.count.toLocaleString("ko-KR")}</span>
        </label>
      ))}
    </fieldset>
  );
}

/** 왼쪽 필터 레일 220px (§3): 검색, 기관(우리 기관 맨 위), 주제, 종류, 상태. 바꾸면 주소가 바뀌고 서버가 다시 거른다. */
export function FilterRail({ query, ours, facets, topicsAvailable }: {
  query: RegQuery; ours: string | null; topicsAvailable: boolean;
  facets: { institution: FacetItem[]; kind: FacetItem[]; status: FacetItem[]; topic: FacetItem[] };
}) {
  const router = useRouter();
  const [q, setQ] = useState(query.q);
  const [open, setOpen] = useState(false);
  const go = (change: Partial<RegQuery>) => router.push(regHref(query, change), { scroll: false });
  const toggle = (key: "inst" | "topic" | "kind", v: string) => {
    const cur = query[key];
    go({ [key]: cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v] });
  };
  const insts = [...facets.institution].sort((a, b) => Number(b.value === ours) - Number(a.value === ours));
  const allInst = query.inst.length === 0;
  return (
    <div>
      <form role="search" onSubmit={(e) => { e.preventDefault(); go({ q: q.trim(), sort: q.trim() ? "" : query.sort }); }}>
        <label className="relative block">
          <span className="sr-only">규정 이름</span>
          <Search aria-hidden="true" className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-fg-subtle" strokeWidth={iconStroke} />
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="규정 이름" className={cn(field, "pl-8")} />
        </label>
      </form>
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
        className="mt-3 inline-flex h-7 items-center gap-1.5 rounded-sm text-small font-medium text-fg-muted lg:hidden">
        <SlidersHorizontal aria-hidden="true" className="size-4" strokeWidth={iconStroke} />필터
      </button>
      <div className={cn(open ? "block" : "hidden", "lg:block")}>
        <Group title="기관" checked={(v) => query.inst.includes(v)} onToggle={(v) => toggle("inst", v)}
          extra={(
            <label className="flex min-h-7 cursor-pointer items-center gap-2 text-small text-fg">
              <Checkbox checked={allInst} disabled={allInst && !ours} onChange={() => go({ inst: allInst && ours ? [ours] : [] })} />
              <span className="flex-1">전체 기관</span>
            </label>
          )}
          items={insts.map((i) => ({ value: i.value, label: i.name ?? i.value, count: i.count, mark: i.value === ours ? "(우리)" : undefined }))} />
        {topicsAvailable ? (
          <Group title="주제" checked={(v) => query.topic.includes(v)} onToggle={(v) => toggle("topic", v)}
            items={facets.topic.map((t) => ({ value: t.value, label: t.label ?? t.value, count: t.count }))} />
        ) : null}
        <Group title="종류" checked={(v) => query.kind.includes(v)} onToggle={(v) => toggle("kind", v)}
          items={facets.kind.map((t) => ({ value: t.value, label: t.label ?? t.value, count: t.count }))} />
        <Group title="상태" checked={(v) => query.status === v || query.status === "all"}
          onToggle={(v) => {
            const on = new Set(query.status === "all" ? ["current", "abolished"] : [query.status]);
            if (on.has(v)) on.delete(v); else on.add(v);
            go({ status: on.size === 2 ? "all" : on.size === 1 ? [...on][0] : "current" });
          }}
          items={facets.status.map((t) => ({ value: t.value, label: t.label ?? t.value, count: t.count }))} />
      </div>
    </div>
  );
}
