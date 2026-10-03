"use client";
import { useRouter } from "next/navigation";
import { SelectMenu } from "@/components/ui/select";
import { regHref, type RegQuery } from "./query";

export function SortSelect({ query, current }: { query: RegQuery; current: string }) {
  const router = useRouter();
  const options = [
    ...(query.q ? [{ value: "relevance", label: "관련도" }] : []),
    { value: "institution", label: "기관순" }, { value: "title", label: "이름순" },
    { value: "recent", label: "최근 시행" }, { value: "articles", label: "조문 많은 순" },
  ];
  return (
    <div className="flex items-center gap-2 text-small text-fg-muted">
      <span id="sort-label">정렬</span>
      <SelectMenu aria-label="정렬" size="sm" className="w-36" options={options} value={current}
        onValueChange={(v) => v && router.push(regHref(query, { sort: v }), { scroll: false })} />
    </div>
  );
}
