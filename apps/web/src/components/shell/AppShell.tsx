"use client";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { cn } from "@/components/ui/cn";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { BreadcrumbsProvider } from "./Breadcrumbs";
import { CommandPaletteProvider } from "./CommandPalette";
import { InstitutionPicker } from "./InstitutionPicker";
import { Sidebar, useSidebarCollapsed } from "./Sidebar";
import { TopBar } from "./TopBar";

/**
 * 앱 셸 (§1): 사이드바 240px(접으면 64px) | 상단 바 48px 위 내용. 768px 아래에서는 사이드바가 왼쪽 시트로.
 * 내용 좌우 여백 16/24/32px, 최대 폭은 화면마다 정한다(규정 보기는 넓게).
 */
export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [collapsed, toggle] = useSidebarCollapsed();
  const [sheetOpen, setSheetOpen] = useState(false);

  // 다른 화면으로 가면 시트를 닫는다 (렌더 중 이전 경로와 비교: effect 안 setState 대신)
  const [lastPath, setLastPath] = useState(pathname);
  if (lastPath !== pathname) {
    setLastPath(pathname);
    setSheetOpen(false);
  }
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 768px)");
    const onChange = () => mq.matches && setSheetOpen(false);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  return (
    <BreadcrumbsProvider>
      <CommandPaletteProvider>
        <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-[var(--z-tooltip)] focus:rounded-sm focus:bg-bg-panel focus:px-3 focus:py-2 focus:text-body focus:shadow-popover">
          본문으로 건너뛰기
        </a>
        <div className="flex min-h-dvh">
          <div className={cn("hidden shrink-0 border-r border-border bg-bg-subtle md:block", collapsed ? "w-16" : "w-60")}>
            <div className="sticky top-0 z-[var(--z-sidebar)] h-dvh">
              <Sidebar collapsed={collapsed} onToggle={toggle} />
            </div>
          </div>
          <div className="flex min-w-0 flex-1 flex-col">
            <TopBar onOpenMenu={() => setSheetOpen(true)} />
            <main id="main" tabIndex={-1} className="w-full flex-1 px-4 pb-12 pt-6 outline-none md:px-6 md:pt-7 xl:px-8">
              {children}
            </main>
          </div>
        </div>
        <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
          <SheetContent side="left" className="bg-bg-subtle">
            <SheetTitle className="sr-only">메뉴</SheetTitle>
            <Sidebar onNavigate={() => setSheetOpen(false)} />
          </SheetContent>
        </Sheet>
        <InstitutionPicker />
      </CommandPaletteProvider>
    </BreadcrumbsProvider>
  );
}
