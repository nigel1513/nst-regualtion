import Link from "next/link";
import * as React from "react";
import { cn } from "./cn";
import { segItem, segOn, segTrack } from "./styles";

/** 주소(?view=)로 상태를 갖는 SegmentedControl. 서버 화면에서 쓴다. */
export function LinkSegmented({ items, value, className, "aria-label": ariaLabel }: {
  items: { value: string; label: React.ReactNode; href: string }[]; value: string; className?: string; "aria-label": string;
}) {
  return (
    <nav aria-label={ariaLabel} className={cn(segTrack, className)}>
      {items.map((it) => (
        <Link key={it.value} href={it.href} scroll={false} aria-current={it.value === value ? "page" : undefined}
          className={cn(segItem, it.value === value && segOn)}>
          {it.label}
        </Link>
      ))}
    </nav>
  );
}
