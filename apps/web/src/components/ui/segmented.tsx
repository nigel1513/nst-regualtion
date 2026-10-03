"use client";
import { Toggle } from "@base-ui/react/toggle";
import { ToggleGroup } from "@base-ui/react/toggle-group";
import * as React from "react";
import { cn } from "./cn";

export type SegmentedItem = { value: string; label: React.ReactNode; icon?: React.ReactNode; disabled?: boolean };

export const segTrack = "inline-flex h-7 items-center gap-0.5 rounded-sm bg-bg-hover p-0.5";
export const segItem = [
  "inline-flex h-6 cursor-pointer select-none items-center gap-1.5 rounded-xs px-2.5 text-small font-medium text-fg-muted outline-none",
  "no-underline hover:text-fg hover:no-underline focus-visible:outline-2 focus-visible:outline-offset-0 focus-visible:outline-focus [&_svg]:size-3.5",
].join(" ");
export const segOn = "bg-bg-raised text-fg shadow-raised";

/** 28px SegmentedControl (§4): 하나는 늘 선택, 화살표 키로 이동, 전환 애니메이션 없음. */
export function SegmentedControl({ items, value, onValueChange, className, "aria-label": ariaLabel }: {
  items: SegmentedItem[]; value: string; onValueChange: (value: string) => void; className?: string; "aria-label": string;
}) {
  return (
    <ToggleGroup value={[value]} onValueChange={(v) => { if (v[0]) onValueChange(v[0]); }} aria-label={ariaLabel} className={cn(segTrack, className)}>
      {items.map((it) => (
        <Toggle key={it.value} value={it.value} disabled={it.disabled}
          className={cn(segItem, "data-[pressed]:bg-bg-raised data-[pressed]:text-fg data-[pressed]:shadow-raised data-[disabled]:cursor-not-allowed data-[disabled]:opacity-50")}>
          {it.icon}
          {it.label}
        </Toggle>
      ))}
    </ToggleGroup>
  );
}
