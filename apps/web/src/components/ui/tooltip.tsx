"use client";
import { Tooltip as Base } from "@base-ui/react/tooltip";
import * as React from "react";
import { cn } from "./cn";

/** 앱에 하나: 첫 툴팁은 500ms 기다리고, 이웃 툴팁은 바로·애니메이션 없이 (data-instant). */
export function TooltipProvider({ children }: { children: React.ReactNode }) {
  return <Base.Provider delay={500} closeDelay={0}>{children}</Base.Provider>;
}

export function Tooltip({ content, children, side = "top", className }: {
  content: React.ReactNode; children: React.ReactElement<Record<string, unknown>>; side?: "top" | "bottom" | "left" | "right"; className?: string;
}) {
  return (
    <Base.Root>
      <Base.Trigger render={children} />
      <Base.Portal>
        <Base.Positioner side={side} sideOffset={6} className="z-[var(--z-tooltip)]">
          <Base.Popup className={cn(
            "max-w-xs rounded-sm bg-primary px-2 py-1 text-caption text-primary-fg",
            "origin-[var(--transform-origin)] transition-[transform,opacity] duration-[var(--dur-press)] ease-[var(--ease-out)]",
            "data-[starting-style]:[transform:scale(0.97)] data-[starting-style]:opacity-0 data-[ending-style]:opacity-0 data-[instant]:transition-none",
            className,
          )}>
            {content}
          </Base.Popup>
        </Base.Positioner>
      </Base.Portal>
    </Base.Root>
  );
}
