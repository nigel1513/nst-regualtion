import type { LucideIcon } from "lucide-react";
import { EmptyState } from "@/components/ui/empty-state";

/** 다른 작업이 채울 화면: 셸 안에서 "준비 중"만 보여 준다. */
export function ComingSoon({ title, icon, description, children }: { title: string; icon: LucideIcon; description: string; children?: React.ReactNode }) {
  return (
    <div className="max-w-[1200px]">
      <h1 className="text-display text-fg">{title}</h1>
      <div className="mt-6 rounded-md border border-border bg-bg-panel">
        <EmptyState icon={icon} title="준비 중" description={description} action={children} />
      </div>
    </div>
  );
}
