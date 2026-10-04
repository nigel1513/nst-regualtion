"use client";
import { UserRound } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { iconStroke } from "@/components/ui/styles";
import { useInstitution } from "@/components/shell/InstitutionContext";
import { useReviewer } from "./reviewer";

/** "내 이름" 단추와 입력 대화상자. 처음 처리하려 할 때도 열린다(open/onOpenChange를 밖에서 줄 수 있다). */
export function NameDialog({ open, onOpenChange, onSaved }: { open: boolean; onOpenChange: (o: boolean) => void; onSaved?: (name: string) => void }) {
  const [name, setName] = useReviewer();
  const [draft, setDraft] = useState("");
  return (
    <Dialog open={open} onOpenChange={(o) => { if (o) setDraft(name ?? ""); onOpenChange(o); }}>
      <DialogContent>
        <DialogTitle className="text-heading text-fg">내 이름</DialogTitle>
        <DialogDescription className="mt-1 text-small text-fg-muted">담당 지정과 처리 기록에 남습니다. 로그인 전까지 이 브라우저에만 저장합니다.</DialogDescription>
        <form className="mt-4 flex flex-col gap-4" onSubmit={(e) => {
          e.preventDefault();
          const v = draft.trim();
          if (!v) return;
          setName(v);
          onOpenChange(false);
          onSaved?.(v);
        }}>
          <label className="flex flex-col gap-1.5 text-small font-medium text-fg">이름
            <Input autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={50} placeholder="예: 김검수" />
          </label>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => onOpenChange(false)}>취소</Button>
            <Button type="submit" variant="primary" disabled={!draft.trim()}>저장</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** 로그인한 사람(목업 로그인)이 담당·처리 기록의 이름이 된다. 로그인 전 화면이나 저장소가 막힌 때만 이름을 묻는다. */
export function MyNameButton() {
  const { user } = useInstitution();
  const [name] = useReviewer();
  const [open, setOpen] = useState(false);
  const shown = user?.name ?? name;
  if (user) {
    return (
      <span className="inline-flex h-8 items-center gap-1.5 text-small text-fg-muted">
        <UserRound aria-hidden="true" className="size-4" strokeWidth={iconStroke} />담당자 <span className="text-fg">{user.name}</span>
      </span>
    );
  }
  return (
    <>
      <Button onClick={() => setOpen(true)}>
        <UserRound aria-hidden="true" strokeWidth={iconStroke} />{shown ? `내 이름: ${shown}` : "내 이름 정하기"}
      </Button>
      <NameDialog open={open} onOpenChange={setOpen} />
    </>
  );
}
