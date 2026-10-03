"use client";
import Link from "next/link";
import { useMemo } from "react";
import { useIsClient, useLocalValue } from "@/lib/hooks";
import { parseRecent, RECENT_KEY } from "@/lib/recent";

export function RecentViewed() {
  const client = useIsClient();
  const raw = useLocalValue(RECENT_KEY);
  const items = useMemo(() => parseRecent(raw), [raw]);
  if (!client) return <div className="h-16" aria-hidden="true" />;
  if (items.length === 0) return <p className="text-small text-fg-muted">아직 본 조문이 없습니다.</p>;
  return (
    <ul className="flex flex-col">
      {items.map((x) => (
        <li key={x.href} className="border-b border-border-subtle last:border-0">
          <Link href={x.href} className="block py-2 text-small">
            <span className="text-fg-muted">{x.title}</span> {x.label}
          </Link>
        </li>
      ))}
    </ul>
  );
}
