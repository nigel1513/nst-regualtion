"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { cn } from "@/components/ui/cn";
import { useIsClient } from "@/lib/hooks";
import { useReviewer } from "./reviewer";
import { reviewHref, type ReviewQuery } from "./types";

/** 숫자 줄 (카드 아님): 열림 · 내 담당 · 담당 없음 · 보류 · 법령 적재 대기. 누르면 그 목록으로. */
export function Numbers({ query, summary }: { query: ReviewQuery; summary: { open: number; hold: number; unassigned: number; law_pending: number } }) {
  const [name] = useReviewer();
  const client = useIsClient();
  const [mine, setMine] = useState<{ name: string; n: number } | null>(null);
  useEffect(() => {
    if (!name) return;
    let alive = true;
    fetch(`/api/v1/review-tasks?${new URLSearchParams({ assignee: name, group: "all", summary: "false", size: "1" })}&status=OPEN&status=HOLD`)
      .then((r) => (r.ok ? r.json() : null)).then((d) => { if (alive && d) setMine({ name, n: d.total }); }).catch(() => {});
    return () => { alive = false; };
  }, [name]);
  const fmt = (n: number) => n.toLocaleString("ko-KR");
  const items: { label: string; value: string; href: string; on: boolean }[] = [
    { label: "열림", value: fmt(summary.open), href: reviewHref(query, { status: "open", assignee: "", law: false }), on: query.status === "open" && !query.assignee && !query.law },
    { label: "내 담당", value: !client ? "" : name ? (mine?.name === name ? fmt(mine.n) : "…") : "—",
      href: name ? reviewHref(query, { status: "open", assignee: name, law: false }) : reviewHref(query), on: !!name && query.assignee === name },
    { label: "담당 없음", value: fmt(summary.unassigned), href: reviewHref(query, { status: "open", assignee: "none", law: false }), on: query.assignee === "none" },
    { label: "보류", value: fmt(summary.hold), href: reviewHref(query, { status: "hold", assignee: "", law: false }), on: query.status === "hold" },
    { label: "법령 적재 대기", value: fmt(summary.law_pending), href: reviewHref(query, { status: "open", assignee: "", law: true }), on: query.law },
  ];
  return (
    <dl className="flex flex-wrap gap-y-3">
      {items.map((x, i) => (
        <div key={x.label} className={cn("pr-6", i < items.length - 1 && "mr-6 border-r border-border-subtle")}>
          <dt className="text-caption text-fg-muted">{x.label}</dt>
          <dd>
            <Link href={x.href} aria-current={x.on ? "true" : undefined}
              className={cn("num text-title no-underline hover:no-underline", x.on ? "text-fg underline decoration-2 underline-offset-4" : "text-fg hover:text-accent-fg")}>
              {x.value || " "}
            </Link>
          </dd>
        </div>
      ))}
    </dl>
  );
}
