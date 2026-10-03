import * as React from "react";
import { cn } from "./cn";

export type Tone = "neutral" | "success" | "warning" | "danger" | "info" | "accent";

/** 면 = 상태 3단계, 글자 = 11단계 (§4 Badge). */
export const toneClass: Record<Tone, string> = {
  neutral: "bg-bg-active text-fg-muted",
  success: "bg-success-soft text-success",
  warning: "bg-warning-soft text-warning",
  danger: "bg-danger-soft text-danger",
  info: "bg-info-soft text-info",
  accent: "bg-accent-soft text-accent-fg",
};

const dotClass: Record<Tone, string> = {
  neutral: "bg-fg-subtle", success: "bg-success-solid", warning: "bg-warning-solid",
  danger: "bg-danger-solid", info: "bg-info-solid", accent: "bg-accent",
};

/** 20px 라벨, 12/500. dot = 6px 점 + 글자(면 없음). */
export function Badge({ tone = "neutral", dot, className, children, ...props }: React.HTMLAttributes<HTMLSpanElement> & { tone?: Tone; dot?: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex h-5 shrink-0 items-center gap-1 whitespace-nowrap rounded-sm text-caption [&_svg]:size-3 [&_svg]:shrink-0",
        dot ? "gap-1.5 px-0 text-fg-muted" : cn("px-1.5", toneClass[tone]),
        className,
      )}
      {...props}
    >
      {dot ? <span aria-hidden="true" className={cn("size-1.5 rounded-full", dotClass[tone])} /> : null}
      {children}
    </span>
  );
}
