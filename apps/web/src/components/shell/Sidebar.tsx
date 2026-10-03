"use client";
import { ChevronsUpDown, Moon, PanelLeftClose, PanelLeftOpen, Sun, SunMoon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import { useCallback, useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/components/ui/cn";
import { InstitutionMark } from "@/components/ui/institution-mark";
import { focusRing, iconStroke } from "@/components/ui/styles";
import { Tooltip } from "@/components/ui/tooltip";
import { ALERTS, NAV, type NavItem } from "@/lib/nav";
import { useInstitution } from "./InstitutionContext";

const COLLAPSE_KEY = "nst-reg-sidebar-collapsed";

/** 접힘(64px 아이콘 레일) 여부를 브라우저에 기억한다. 저장소가 막혀 있으면 이 페이지에서만. */
export function useSidebarCollapsed(): [boolean, () => void] {
  const [collapsed, setCollapsed] = useState(false);
  useEffect(() => {
    try {
      if (window.localStorage.getItem(COLLAPSE_KEY) === "1") setCollapsed(true);
    } catch {
      /* 펼친 채로 */
    }
  }, []);
  const toggle = useCallback(() => {
    setCollapsed((c) => {
      try {
        window.localStorage.setItem(COLLAPSE_KEY, c ? "0" : "1");
      } catch {
        /* 이 페이지에서만 */
      }
      return !c;
    });
  }, []);
  return [collapsed, toggle];
}

const row = (compact: boolean) => cn("flex h-8 items-center gap-2.5 rounded-sm text-body font-medium no-underline hover:no-underline", compact ? "w-8 justify-center" : "px-2.5");

function NavLink({ item, active, compact, onNavigate }: { item: NavItem; active: boolean; compact: boolean; onNavigate?: () => void }) {
  const Icon = item.icon;
  const link = (
    <Link href={item.href} aria-current={active ? "page" : undefined} onClick={onNavigate}
      className={cn(row(compact), focusRing, active ? "bg-bg-active text-fg hover:text-fg" : "text-fg-muted hover:bg-bg-hover hover:text-fg")}>
      <Icon aria-hidden="true" className="size-4 shrink-0" strokeWidth={iconStroke} />
      <span className={compact ? "sr-only" : "min-w-0 flex-1 truncate"}>{item.label}</span>
    </Link>
  );
  return compact ? <Tooltip content={item.label} side="right">{link}</Tooltip> : link;
}

function ThemeButton({ compact }: { compact: boolean }) {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const order = ["system", "light", "dark"] as const;
  const cur = mounted ? ((theme as (typeof order)[number]) ?? "system") : "system";
  const next = order[(order.indexOf(cur) + 1) % order.length];
  const label = { system: "시스템 테마", light: "밝은 테마", dark: "어두운 테마" }[cur];
  const Icon = { system: SunMoon, light: Sun, dark: Moon }[cur];
  const btn = (
    <button type="button" onClick={() => setTheme(next)} aria-label={`${label} (바꾸기)`}
      className={cn(row(compact), focusRing, "press w-full cursor-pointer text-fg-muted hover:bg-bg-hover hover:text-fg", compact && "w-8")}>
      <Icon aria-hidden="true" className="size-4 shrink-0" strokeWidth={iconStroke} />
      <span className={compact ? "sr-only" : "min-w-0 flex-1 truncate text-left"}>{label}</span>
    </button>
  );
  return compact ? <Tooltip content={label} side="right">{btn}</Tooltip> : btn;
}

/** 왼쪽 내비 (§1): 240px bg-subtle, 접으면 64px 레일. 모바일 시트 안에서는 늘 펼친 모양. */
export function Sidebar({ collapsed = false, onToggle, onNavigate }: { collapsed?: boolean; onToggle?: () => void; onNavigate?: () => void }) {
  const pathname = usePathname();
  const { current, setPickerOpen } = useInstitution();
  const AlertIcon = ALERTS.icon;
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className={cn("flex h-12 shrink-0 items-center gap-2", collapsed ? "justify-center px-2" : "pl-4 pr-2")}>
        <Link href="/" onClick={onNavigate} className={cn("flex min-w-0 items-center gap-2 rounded-sm no-underline hover:no-underline", focusRing)}>
          <span aria-hidden="true" className="flex size-[22px] shrink-0 items-center justify-center rounded-sm bg-primary text-micro font-bold text-primary-fg">N</span>
          <span className={collapsed ? "sr-only" : "truncate text-body font-semibold text-fg"}>출연연 규정</span>
        </Link>
        {onToggle && !collapsed ? (
          <button type="button" onClick={onToggle} aria-label="사이드바 접기"
            className={cn("press ml-auto inline-flex size-7 cursor-pointer items-center justify-center rounded-sm text-fg-muted hover:bg-bg-hover hover:text-fg", focusRing)}>
            <PanelLeftClose aria-hidden="true" className="size-4" strokeWidth={iconStroke} />
          </button>
        ) : null}
      </div>
      {onToggle && collapsed ? (
        <div className="flex shrink-0 justify-center pb-1">
          <button type="button" onClick={onToggle} aria-label="사이드바 펼치기"
            className={cn("press inline-flex size-8 cursor-pointer items-center justify-center rounded-sm text-fg-muted hover:bg-bg-hover hover:text-fg", focusRing)}>
            <PanelLeftOpen aria-hidden="true" className="size-4" strokeWidth={iconStroke} />
          </button>
        </div>
      ) : null}
      <nav aria-label="주 메뉴" className={cn("flex min-h-0 flex-1 flex-col overflow-y-auto pb-3", collapsed ? "items-center px-4" : "px-2")}>
        <ul className="flex flex-col gap-px">
          {NAV.map((item) => (
            <li key={item.href}><NavLink item={item} active={item.match(pathname)} compact={collapsed} onNavigate={onNavigate} /></li>
          ))}
        </ul>
        <div className={cn("mt-4", collapsed && "w-8")}>
          {collapsed ? <div aria-hidden="true" className="mb-3 h-px bg-border" /> : (
            <span className="flex h-7 items-center px-2.5 text-caption text-fg-muted">우리 기관</span>
          )}
          <button type="button" onClick={() => setPickerOpen(true)} aria-label={`우리 기관: ${current?.name ?? "선택 안 함"} (바꾸기)`}
            className={cn(row(collapsed), focusRing, "press w-full cursor-pointer text-left text-fg hover:bg-bg-hover", collapsed && "w-8")}>
            {current ? <InstitutionMark code={current.code} /> : (
              <span aria-hidden="true" className="flex size-[22px] shrink-0 items-center justify-center rounded-sm border border-dashed border-border-strong text-micro text-fg-muted">–</span>
            )}
            {!collapsed ? (
              <>
                <span className={cn("min-w-0 flex-1 truncate", !current && "text-fg-muted")}>{current?.name ?? "전체 기관"}</span>
                <ChevronsUpDown aria-hidden="true" className="size-3.5 shrink-0 text-fg-muted" strokeWidth={iconStroke} />
              </>
            ) : null}
          </button>
        </div>
        <div className="flex-1" />
        <div className={cn("flex flex-col gap-px", collapsed && "items-center")}>
          <ThemeButton compact={collapsed} />
          <span aria-disabled="true" className={cn(row(collapsed), "cursor-default text-fg-subtle")} title="개정 알림 · 준비 중">
            <AlertIcon aria-hidden="true" className="size-4 shrink-0" strokeWidth={iconStroke} />
            <span className={collapsed ? "sr-only" : "min-w-0 flex-1 truncate"}>{ALERTS.label}</span>
            {!collapsed ? <Badge>준비 중</Badge> : null}
          </span>
        </div>
      </nav>
    </div>
  );
}
