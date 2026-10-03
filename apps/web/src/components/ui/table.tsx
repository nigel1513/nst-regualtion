import * as React from "react";
import { cn } from "./cn";
import { focusRing } from "./styles";

/** 경계 상자 안 표: 머리 bg-subtle 12/500, 행 36px, 1px 구분선. 넓으면 상자 안에서 가로 스크롤. */
export function Table({ caption, className, frameClassName, children }: {
  caption: string; className?: string; frameClassName?: string; children: React.ReactNode;
}) {
  return (
    // 표가 상자보다 넓을 때 키보드로도 스크롤할 수 있게 (axe scrollable-region-focusable)
    <div role="region" aria-label={caption} tabIndex={0} className={cn("relative w-full overflow-x-auto rounded-md border border-border bg-bg-panel", focusRing, frameClassName)}>
      <table className={cn("w-full border-collapse text-small", className)}>
        <caption className="sr-only">{caption}</caption>
        {children}
      </table>
    </div>
  );
}
export function THead({ className, ...props }: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <thead className={cn("bg-bg-subtle text-left", className)} {...props} />;
}
export function TBody(props: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody {...props} />;
}
export function Tr({ className, ...props }: React.HTMLAttributes<HTMLTableRowElement>) {
  return <tr className={cn("border-b border-border-subtle last:border-0", className)} {...props} />;
}
export function Th({ className, scope = "col", ...props }: React.ThHTMLAttributes<HTMLTableCellElement>) {
  return <th scope={scope} className={cn("h-9 whitespace-nowrap border-b border-border px-3 text-left text-caption text-fg-muted", className)} {...props} />;
}
export function Td({ className, ...props }: React.TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn("px-3 py-2 align-top text-fg", className)} {...props} />;
}
