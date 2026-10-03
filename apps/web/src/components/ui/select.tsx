"use client";
import { Select as Base } from "@base-ui/react/select";
import { Check, ChevronDown } from "lucide-react";
import * as React from "react";
import { cn } from "./cn";
import { field, floating, iconStroke, listItem } from "./styles";

export type SelectOption = { value: string; label: React.ReactNode; disabled?: boolean };

/** Base UI 셀렉트 (§4 Select): 트리거는 Input과 같은 치수, 고른 항목에 체크, 키보드 이동. */
export function SelectMenu({ options, value, onValueChange, placeholder, className, size = "md", ...aria }: {
  options: SelectOption[]; value?: string | null; onValueChange?: (value: string | null) => void; placeholder?: React.ReactNode;
  className?: string; size?: "sm" | "md"; "aria-label"?: string; id?: string;
}) {
  return (
    <Base.Root items={options} value={value} onValueChange={(v) => onValueChange?.(v as string | null)}>
      <Base.Trigger className={cn(field, "flex cursor-default items-center justify-between gap-2 text-left", size === "sm" && "h-7 text-small", className)} {...aria}>
        <Base.Value className="min-w-0 truncate data-[placeholder]:text-fg-subtle" placeholder={placeholder} />
        <Base.Icon className="shrink-0 text-fg-muted"><ChevronDown aria-hidden="true" className="size-4" strokeWidth={iconStroke} /></Base.Icon>
      </Base.Trigger>
      <Base.Portal>
        <Base.Positioner alignItemWithTrigger={false} sideOffset={4} collisionPadding={8} className="z-[var(--z-popover)]">
          <Base.Popup className={cn(floating, "max-h-[min(var(--available-height),20rem)] min-w-[var(--anchor-width)] overflow-y-auto p-1")}>
            <Base.List>
              {options.map((o) => (
                <Base.Item key={o.value} value={o.value} disabled={o.disabled} className={cn(listItem, "pr-8")}>
                  <Base.ItemText className="min-w-0 flex-1 truncate">{o.label}</Base.ItemText>
                  <Base.ItemIndicator className="absolute right-2 text-fg"><Check aria-hidden="true" strokeWidth={2} /></Base.ItemIndicator>
                </Base.Item>
              ))}
            </Base.List>
          </Base.Popup>
        </Base.Positioner>
      </Base.Portal>
    </Base.Root>
  );
}
