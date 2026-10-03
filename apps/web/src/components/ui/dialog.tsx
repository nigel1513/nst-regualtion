"use client";
import { Dialog as Base } from "@base-ui/react/dialog";
import * as React from "react";
import { cn } from "./cn";
import { scrimClass } from "./sheet";

export const Dialog = Base.Root;
export const DialogTitle = Base.Title;
export const DialogDescription = Base.Description;
export const DialogClose = Base.Close;

/** 가운데 대화상자 (§4 Dialog): 480px, 반경 lg, 가운데 기준 scale(0.98)+opacity 200ms. */
export function DialogContent({ className, children, ...props }: React.ComponentProps<typeof Base.Popup>) {
  return (
    <Base.Portal>
      <Base.Backdrop className={scrimClass} />
      <Base.Viewport className="fixed inset-0 z-[var(--z-dialog)] flex items-center justify-center p-4">
        <Base.Popup
          className={cn(
            "relative flex max-h-[calc(100dvh-2rem)] w-full max-w-[480px] flex-col overflow-y-auto rounded-lg border border-border bg-bg-panel p-6 text-fg shadow-dialog outline-none",
            "transition-[transform,opacity] duration-[var(--dur-base)] ease-[var(--ease-out)]",
            "data-[starting-style]:[transform:scale(0.98)] data-[starting-style]:opacity-0",
            "data-[ending-style]:[transform:scale(0.98)] data-[ending-style]:opacity-0 data-[ending-style]:duration-[var(--dur-fast)]",
            className,
          )}
          {...props}
        >
          {children}
        </Base.Popup>
      </Base.Viewport>
    </Base.Portal>
  );
}
