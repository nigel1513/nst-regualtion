"use client";
import Link from "next/link";
import { useEffect, useRef } from "react";
import { cn } from "@/components/ui/cn";
import type { Citation } from "@/lib/chat";

/** 오른쪽 레일 "근거 N" (Harvey식): 번호 · 기관 · 조문 · 원문 그대로의 인용(강조). 누르면 그 조·항으로. */
export function CitationRail({ items, active }: { items: Citation[]; active: number | null }) {
  const box = useRef<HTMLOListElement>(null);
  useEffect(() => {
    if (active == null) return;
    box.current?.querySelector(`[data-n="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);
  return (
    <section aria-labelledby="cite-h">
      <h2 id="cite-h" className="mb-2 text-caption text-fg-muted">근거 <span className="num">{items.length}</span></h2>
      {items.length === 0 ? <p className="text-small text-fg-muted">답에 쓴 조문이 여기에 원문 그대로 나옵니다.</p> : (
        <ol ref={box} className="flex flex-col gap-2">
          {items.map((c) => (
            <li key={c.n} data-n={c.n}
              className={cn("rounded-md border bg-bg-panel px-3.5 py-3", active === c.n ? "border-focus ring-3 ring-focus-ring" : "border-border")}>
              <div className="flex items-start gap-1.5 text-small font-semibold text-fg">
                <span className="num inline-flex h-5 min-w-5 shrink-0 items-center justify-center rounded-sm bg-accent-soft px-1 text-caption text-accent-fg">{c.n}</span>
                <Link href={c.href} className="text-fg hover:text-fg">{c.institution.name ? `${c.institution.name} · ` : ""}{c.label}</Link>
              </div>
              <blockquote className="mt-1.5 text-small text-fg">“<mark className="rounded-xs bg-mark text-inherit">{c.quote}</mark>”</blockquote>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
