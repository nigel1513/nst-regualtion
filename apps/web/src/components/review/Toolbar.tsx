"use client";
import { Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { cn } from "@/components/ui/cn";
import { SelectMenu } from "@/components/ui/select";
import { field, iconStroke } from "@/components/ui/styles";
import { useReviewer } from "./reviewer";
import { KIND_LABEL, reviewHref, type ReviewQuery } from "./types";

/** 툴바: 기관 · 종류 · 담당 필터와 검색 (상태는 서버 쪽 SegmentedControl). */
export function Toolbar({ query, insts }: { query: ReviewQuery; insts: { code: string; name: string; count: number }[] }) {
  const router = useRouter();
  const [name] = useReviewer();
  const [q, setQ] = useState(query.q);
  const go = (c: Partial<ReviewQuery>) => router.push(reviewHref(query, c), { scroll: false });
  return (
    <div className="flex flex-wrap items-center gap-2">
      <SelectMenu aria-label="기관" size="sm" className="w-44" value={query.inst || "all"} onValueChange={(v) => go({ inst: v === "all" ? "" : v ?? "" })}
        options={[{ value: "all", label: "기관: 전체" }, ...insts.map((i) => ({ value: i.code, label: `${i.name} ${i.count.toLocaleString("ko-KR")}` }))]} />
      <SelectMenu aria-label="종류" size="sm" className="w-40" value={query.kind || "all"} onValueChange={(v) => go({ kind: v === "all" ? "" : v ?? "" })}
        options={[{ value: "all", label: "종류: 전체" }, ...Object.entries(KIND_LABEL).map(([k, l]) => ({ value: k, label: l }))]} />
      <SelectMenu aria-label="담당" size="sm" className="w-36"
        value={!query.assignee ? "all" : query.assignee === "none" ? "none" : query.assignee === name ? "me" : "other"}
        onValueChange={(v) => go({ assignee: v === "none" ? "none" : v === "me" && name ? name : "" })}
        options={[{ value: "all", label: "담당: 전체" }, ...(name ? [{ value: "me", label: "내 담당" }] : []), { value: "none", label: "담당 없음" },
          ...(query.assignee && query.assignee !== "none" && query.assignee !== name ? [{ value: "other", label: `담당: ${query.assignee}` }] : [])]} />
      <form role="search" className="min-w-0 flex-1 sm:max-w-64" onSubmit={(e) => { e.preventDefault(); go({ q: q.trim() }); }}>
        <label className="relative block">
          <span className="sr-only">규정 이름·인용 찾기</span>
          <Search aria-hidden="true" className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-fg-subtle" strokeWidth={iconStroke} />
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="규정 이름·인용 찾기" className={cn(field, "h-7 pl-8 text-small")} />
        </label>
      </form>
    </div>
  );
}
