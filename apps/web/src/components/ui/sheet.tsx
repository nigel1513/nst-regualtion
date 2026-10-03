"use client";
import { Dialog as Base } from "@base-ui/react/dialog";
import { X } from "lucide-react";
import * as React from "react";
import { cn } from "./cn";
import { focusRing, iconStroke } from "./styles";

export const Sheet = Base.Root;
export const SheetTitle = Base.Title;

export const scrimClass =
  "fixed inset-0 z-[var(--z-dialog)] bg-scrim transition-opacity duration-[var(--dur-fast)] ease-[var(--ease-out)] data-[starting-style]:opacity-0 data-[ending-style]:opacity-0";

/** 가장자리 시트 (§4 Sheet): 왼쪽 280px 모바일 내비. 280ms drawer 곡선으로 들어오고 같은 방향으로 나간다. */
export function SheetContent({ side = "left", className, children, closeLabel = "닫기", ...props }:
  React.ComponentProps<typeof Base.Popup> & { side?: "left" | "right"; closeLabel?: string }) {
  return (
    <Base.Portal>
      <Base.Backdrop className={scrimClass} />
      <Base.Popup
        className={cn(
          "fixed inset-y-0 z-[var(--z-dialog)] flex w-full flex-col overflow-y-auto border-border bg-bg-panel text-fg shadow-dialog outline-none",
          "transition-transform duration-[var(--dur-sheet)] ease-[var(--ease-drawer)]",
          side === "right"
            ? "right-0 max-w-[480px] border-l data-[starting-style]:translate-x-full data-[ending-style]:translate-x-full"
            : "left-0 max-w-[280px] border-r data-[starting-style]:-translate-x-full data-[ending-style]:-translate-x-full",
          className,
        )}
        {...props}
      >
        {children}
        <Base.Close aria-label={closeLabel} className={cn("press absolute right-3 top-3 inline-flex size-7 cursor-pointer items-center justify-center rounded-sm text-fg-muted hover:bg-bg-hover hover:text-fg", focusRing)}>
          <X aria-hidden="true" className="size-4" strokeWidth={iconStroke} />
        </Base.Close>
      </Base.Popup>
    </Base.Portal>
  );
}
