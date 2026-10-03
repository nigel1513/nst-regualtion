import * as React from "react";
import { cn } from "./cn";

/** 키캡: 모노 11px, 1px 경계, 반경 4px (유일한 예외). */
export function Kbd({ className, ...props }: React.HTMLAttributes<HTMLElement>) {
  return (
    <kbd
      className={cn(
        "inline-flex h-5 min-w-5 items-center justify-center rounded-xs border border-border bg-bg-subtle px-1 font-mono text-micro leading-none text-fg-muted",
        className,
      )}
      {...props}
    />
  );
}
