"use client";
import { Slash } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { cn } from "@/components/ui/cn";
import { sectionFor } from "@/lib/nav";

export type Crumb = { label: string; href?: string };

const SetCrumbs = createContext<(items: Crumb[] | null) => void>(() => {});
const CrumbsCtx = createContext<Crumb[] | null>(null);

export function BreadcrumbsProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Crumb[] | null>(null);
  return (
    <SetCrumbs.Provider value={setItems}>
      <CrumbsCtx.Provider value={items}>{children}</CrumbsCtx.Provider>
    </SetCrumbs.Provider>
  );
}

/** 서버 화면이 자기 경로(구역 뒤)를 알린다: <Crumbs items={[{label: "한국천문연구원"}, {label: "여비규정"}]} /> */
export function Crumbs({ items }: { items: Crumb[] }) {
  const set = useContext(SetCrumbs);
  const key = JSON.stringify(items);
  useEffect(() => {
    set(JSON.parse(key) as Crumb[]);
    return () => set(null);
  }, [key, set]);
  return null;
}

/** 상단 바 경로: 마지막만 --fg, 나머지는 링크(--fg-muted), 구분자 /. 휴대폰은 마지막 하나만. */
export function Breadcrumbs({ className }: { className?: string }) {
  const pathname = usePathname();
  const extra = useContext(CrumbsCtx) ?? [];
  const section = sectionFor(pathname);
  const trail: Crumb[] = [...(section ? [{ label: section.label, href: section.href }] : []), ...extra];
  if (!trail.length) return <div className={className} />;
  return (
    <nav aria-label="현재 위치" className={cn("min-w-0", className)}>
      <ol className="flex min-w-0 items-center gap-1.5 text-small">
        {trail.map((c, i) => {
          const last = i === trail.length - 1;
          return (
            <li key={`${i}-${c.label}`} className={cn("min-w-0 items-center gap-1.5", last ? "flex" : "hidden md:flex")}>
              {i > 0 ? <Slash aria-hidden="true" className="hidden size-3.5 shrink-0 -rotate-12 text-border-strong md:block" strokeWidth={1.75} /> : null}
              {last ? (
                <span aria-current="page" className="truncate font-medium text-fg">{c.label}</span>
              ) : c.href ? (
                <Link href={c.href} className="max-w-60 truncate rounded-xs text-fg-muted hover:text-fg hover:no-underline">{c.label}</Link>
              ) : (
                <span className="max-w-60 truncate text-fg-muted">{c.label}</span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
