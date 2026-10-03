"use client";
import { Toggle } from "@base-ui/react/toggle";
import { ToggleGroup } from "@base-ui/react/toggle-group";
import * as React from "react";
import { cn } from "./cn";
import { segItem, segTrack } from "./styles";

export type SegmentedItem = { value: string; label: React.ReactNode; icon?: React.ReactNode; disabled?: boolean };

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
