import Link from "next/link";
import * as React from "react";
import { cn } from "./cn";

/** 밑줄 탭 (§4): 40px, 14/500, 선택 = --fg 글자 + 2px --fg 밑줄. 주소(?tab=)와 맞춘다. 전환 애니메이션 없음. */
export function LinkTabs({ items, value, className, "aria-label": ariaLabel }: {
  items: { value: string; label: React.ReactNode; href: string; count?: number }[]; value: string; className?: string; "aria-label": string;
}) {
  return (
    <nav aria-label={ariaLabel} className={cn("flex gap-6 overflow-x-auto border-b border-border [scrollbar-width:none]", className)}>
      {items.map((it) => {
        const on = it.value === value;
        return (
          <Link key={it.value} href={it.href} scroll={false} aria-current={on ? "page" : undefined}
            className={cn(
              "relative flex h-10 shrink-0 items-center gap-1.5 whitespace-nowrap text-body font-medium no-underline hover:no-underline",
              "after:absolute after:inset-x-0 after:bottom-0 after:h-0.5 after:rounded-t-sm",
              on ? "text-fg after:bg-fg hover:text-fg" : "text-fg-muted after:bg-transparent hover:text-fg",
              "focus-visible:rounded-sm focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus",
            )}>
            {it.label}
            {it.count !== undefined ? <span className="num rounded-sm bg-bg-active px-1.5 text-caption text-fg-muted">{it.count}</span> : null}
          </Link>
        );
      })}
    </nav>
  );
}
