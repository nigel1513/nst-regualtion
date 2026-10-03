"use client";
import { Check, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/components/ui/cn";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { InstitutionMark } from "@/components/ui/institution-mark";
import { field, iconStroke } from "@/components/ui/styles";
import { useInstitution } from "./InstitutionContext";

/** 우리 기관 고르기 (§1): 처음 방문 때 열리고, 사이드바 "우리 기관"으로 다시 연다. 건너뛰면 전체. */
export function InstitutionPicker() {
  const { insts, inst, choose, pickerOpen, setPickerOpen } = useInstitution();
  const [q, setQ] = useState("");
  const list = useMemo(() => {
    const t = q.trim();
    const rows = t ? insts.filter((i) => i.name.includes(t) || i.code.toLowerCase().includes(t.toLowerCase())) : insts;
    return [...rows].sort((a, b) => Number(b.works > 0) - Number(a.works > 0));
  }, [insts, q]);
  return (
    <Dialog open={pickerOpen} onOpenChange={setPickerOpen}>
      <DialogContent className="max-w-[440px] gap-0 p-0">
        <div className="px-5 pb-3 pt-5">
          <DialogTitle className="text-heading text-fg">우리 기관</DialogTitle>
          <DialogDescription className="mt-1 text-small text-fg-muted">홈과 규정 찾기가 이 기관을 먼저 보여 줍니다. 나중에 사이드바에서 바꿀 수 있습니다.</DialogDescription>
          <label className="relative mt-3 block">
            <span className="sr-only">기관 이름</span>
            <Search aria-hidden="true" className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-fg-subtle" strokeWidth={iconStroke} />
            <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="기관 이름" className={cn(field, "pl-8")} />
          </label>
        </div>
        <ul className="max-h-[min(360px,50dvh)] overflow-y-auto border-y border-border px-2 py-1" aria-label="기관 목록">
          {list.map((i) => (
            <li key={i.code}>
              <button type="button" onClick={() => choose(i.code)}
                className="flex h-9 w-full cursor-pointer items-center gap-2.5 rounded-sm px-2 text-left text-body text-fg hover:bg-bg-hover">
                <InstitutionMark code={i.code} />
                <span className="min-w-0 flex-1 truncate">{i.name}</span>
                {i.works > 0 ? <span className="num text-small text-fg-muted">{i.works.toLocaleString("ko-KR")}</span>
                  : <span className="text-caption text-fg-subtle">수집 전</span>}
                {inst === i.code ? <Check aria-hidden="true" className="size-4 text-fg" strokeWidth={2} /> : null}
              </button>
            </li>
          ))}
          {list.length === 0 ? <li className="px-2 py-6 text-center text-small text-fg-muted">맞는 기관이 없습니다</li> : null}
        </ul>
        <div className="flex justify-end gap-2 px-5 py-3">
          <Button variant="ghost" onClick={() => choose(null)}>건너뛰기 (전체 기관)</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
