"use client";
import { Plus, Search, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { buttonClass } from "@/components/ui/button";
import { cn } from "@/components/ui/cn";
import { Checkbox } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { SelectMenu } from "@/components/ui/select";
import { field, iconStroke } from "@/components/ui/styles";
import { compareHref, type CompareQuery } from "./query";

const MAX_OTHERS = 5;

export function TopicSelect({ query, topics }: { query: CompareQuery; topics: { id: string; label: string }[] }) {
  const router = useRouter();
  return (
    <SelectMenu aria-label="주제" className="w-48" value={query.topic || null} placeholder="주제 고르기"
      onValueChange={(v) => v && router.push(compareHref(query, { topic: v, item: "", inst: [] }))}
      options={topics.map((t) => ({ value: t.id, label: t.label }))} />
  );
}

/** 비교 기관 칩: 우리 기관은 첫 열로 고정, 다른 기관은 빼거나 최대 5곳까지 더한다. */
export function InstitutionChips({ query, shown, insts }: {
  query: CompareQuery; shown: { code: string; name: string; ours: boolean }[]; insts: { code: string; name: string; works: number }[];
}) {
  const router = useRouter();
  const [q, setQ] = useState("");
  const others = shown.filter((i) => !i.ours).map((i) => i.code);
  const ours = shown.find((i) => i.ours);
  const go = (next: string[]) => router.push(compareHref(query, { inst: next.length ? next : ours ? [ours.code] : [] }), { scroll: false });
  const pick = useMemo(() => insts.filter((i) => i.works > 0 && !shown.some((s) => s.code === i.code)
    && (!q.trim() || i.name.includes(q.trim()) || i.code.toLowerCase().includes(q.trim().toLowerCase()))), [insts, shown, q]);
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="mr-1 text-caption text-fg-muted">비교 기관</span>
      {shown.map((i) => i.ours ? (
        <Badge key={i.code} tone="accent" className="h-6 px-2 text-small">{i.name} (우리)</Badge>
      ) : (
        <span key={i.code} className="inline-flex h-6 items-center gap-1 rounded-sm bg-bg-active pl-2 pr-0.5 text-small text-fg">
          {i.name}
          <button type="button" aria-label={`${i.name} 빼기`} onClick={() => go(others.filter((c) => c !== i.code))}
            className="inline-flex size-5 cursor-pointer items-center justify-center rounded-xs text-fg-muted hover:bg-bg-hover hover:text-fg">
            <X aria-hidden="true" className="size-3" strokeWidth={iconStroke} />
          </button>
        </span>
      ))}
      {others.length < MAX_OTHERS ? (
        <Popover>
          <PopoverTrigger className={buttonClass("ghost", "sm", "h-6 px-1.5 text-accent-fg hover:text-accent-fg")}>
            <Plus aria-hidden="true" strokeWidth={iconStroke} />기관 추가
          </PopoverTrigger>
          <PopoverContent className="w-72 p-2">
            <label className="relative block">
              <span className="sr-only">기관 찾기</span>
              <Search aria-hidden="true" className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-fg-subtle" strokeWidth={iconStroke} />
              <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="기관 이름" className={cn(field, "pl-8")} />
            </label>
            <ul className="mt-1 max-h-64 overflow-y-auto" aria-label="더할 기관">
              {pick.map((i) => (
                <li key={i.code}>
                  <button type="button" onClick={() => go([...others, i.code])}
                    className="flex h-8 w-full cursor-pointer items-center rounded-sm px-2 text-left text-small hover:bg-bg-hover">{i.name}</button>
                </li>
              ))}
              {pick.length === 0 ? <li className="px-2 py-3 text-small text-fg-muted">더할 기관이 없습니다</li> : null}
            </ul>
            <p className="px-2 pb-1 pt-1.5 text-caption font-normal text-fg-muted">우리 기관 외 최대 {MAX_OTHERS}곳</p>
          </PopoverContent>
        </Popover>
      ) : null}
    </div>
  );
}

export function DiffOnly({ query }: { query: CompareQuery }) {
  const router = useRouter();
  return (
    <label className="flex cursor-pointer items-center gap-2 text-small text-fg">
      <Checkbox checked={query.diff} onChange={() => router.push(compareHref(query, { diff: !query.diff }), { scroll: false })} />차이만 보기
    </label>
  );
}

export function ItemSelect({ query, items }: { query: CompareQuery; items: { id: string; label: string }[] }) {
  const router = useRouter();
  return (
    <SelectMenu aria-label="비교 항목" className="w-60" value={query.item || items[0]?.id || null}
      onValueChange={(v) => v && router.push(compareHref(query, { item: v }), { scroll: false })}
      options={items.map((i) => ({ value: i.id, label: i.label }))} />
  );
}
