"use client";
import { Menu, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { buttonClass } from "@/components/ui/button";
import { cn } from "@/components/ui/cn";
import { Kbd } from "@/components/ui/kbd";
import { focusRing, iconStroke } from "@/components/ui/styles";
import { Breadcrumbs } from "./Breadcrumbs";
import { useCommandPalette } from "./CommandPalette";

/** 애플 키보드는 ⌘, 아니면 Ctrl. 마운트 전에는 모른다(자리만 잡아 둔다). */
function useModKey(): "⌘" | "Ctrl" | null {
  const [mod, setMod] = useState<"⌘" | "Ctrl" | null>(null);
  useEffect(() => {
    const p = (navigator as Navigator & { userAgentData?: { platform?: string } }).userAgentData?.platform ?? navigator.platform ?? "";
    setMod(/mac|iphone|ipad/i.test(p) ? "⌘" : "Ctrl");
  }, []);
  return mod;
}

/** 48px 불투명 상단 바 (§1): 왼쪽 경로, 오른쪽 ⌘K 찾기. 휴대폰은 메뉴 버튼이 시트를 연다. */
export function TopBar({ onOpenMenu }: { onOpenMenu: () => void }) {
  const { setOpen } = useCommandPalette();
  const mod = useModKey();
  return (
    <header className="sticky top-0 z-[var(--z-header)] flex h-12 shrink-0 items-center gap-2 border-b border-border bg-bg px-4 md:px-6 xl:px-8">
      <button type="button" onClick={onOpenMenu} aria-label="메뉴 열기"
        className={cn("press -ml-1.5 inline-flex size-8 cursor-pointer items-center justify-center rounded-sm text-fg-muted hover:bg-bg-hover hover:text-fg md:hidden", focusRing)}>
        <Menu aria-hidden="true" className="size-4" strokeWidth={iconStroke} />
      </button>
      <Breadcrumbs className="flex-1" />
      <button type="button" onClick={() => setOpen(true)} aria-keyshortcuts="Meta+K Control+K"
        className={buttonClass("secondary", "md",
          "w-8 justify-center px-0 text-fg-muted max-md:border-transparent max-md:bg-transparent md:w-72 md:justify-start md:px-2.5")}>
        <Search aria-hidden="true" strokeWidth={iconStroke} />
        <span className="sr-only md:not-sr-only md:flex-1 md:text-left md:font-normal">규정 찾기 또는 질문</span>
        <Kbd aria-hidden="true" className={cn("hidden md:inline-flex", !mod && "invisible")}>{mod === "⌘" ? "⌘K" : "Ctrl K"}</Kbd>
      </button>
    </header>
  );
}
