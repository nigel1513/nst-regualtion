"use client";
import { Popover as Base } from "@base-ui/react/popover";
import * as React from "react";
import { cn } from "./cn";
import { floating } from "./styles";

export const Popover = Base.Root;
export const PopoverTrigger = Base.Trigger;
export const PopoverClose = Base.Close;

/** 트리거에 붙는 떠 있는 면. 층은 --z-popover. */
export function PopoverContent({ className, side = "bottom", align = "start", sideOffset = 6, ...props }:
  React.ComponentProps<typeof Base.Popup> & { side?: "top" | "bottom" | "left" | "right"; align?: "start" | "center" | "end"; sideOffset?: number }) {
  return (
    <Base.Portal>
      <Base.Positioner side={side} align={align} sideOffset={sideOffset} collisionPadding={8} className="z-[var(--z-popover)]">
        <Base.Popup className={cn(floating, "max-w-[calc(100vw-1rem)] p-4", className)} {...props} />
      </Base.Positioner>
    </Base.Portal>
  );
}

export function PopoverTitle({ className, ...props }: React.ComponentProps<typeof Base.Title>) {
  return <Base.Title className={cn("text-body font-semibold text-fg", className)} {...props} />;
}
