import type { LucideIcon } from "lucide-react";
import * as React from "react";
import { cn } from "./cn";
import { iconStroke } from "./styles";

/** 20px 아이콘(원형 바탕) + 14/600 제목 + 한 줄 설명 + 행동 하나 (§4). 일러스트 없음. */
export function EmptyState({ icon: Icon, title, description, action, className, align = "center" }: {
  icon?: LucideIcon; title: string; description?: React.ReactNode; action?: React.ReactNode; className?: string;
  align?: "center" | "start";
}) {
  return (
    <div className={cn("flex flex-col py-12", align === "center" ? "items-center px-6 text-center" : "items-start", className)}>
      {Icon ? (
        <span className="mb-3 flex size-10 items-center justify-center rounded-full bg-bg-hover text-fg-muted">
          <Icon aria-hidden="true" className="size-5" strokeWidth={iconStroke} />
        </span>
      ) : null}
      <p className="text-body font-semibold text-fg">{title}</p>
      {description ? <p className="mt-1 max-w-sm text-small text-fg-muted">{description}</p> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}
