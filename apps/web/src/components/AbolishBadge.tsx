import { Badge } from "@/components/ui/badge";
import { fmtDate } from "@/lib/format";

export const ABOLISH_TASK_LABEL: Record<string, string> = { ABOLISHED: "폐지 확인" };

/** 폐지(확정)는 빨강, 폐지 후보(ALIO 목록에서 3일 연속 사라짐, 사람 확인 대기)는 주황. 현행이면 아무것도 그리지 않는다. */
export function AbolishBadge({ status, abolishedOn }: { status?: string | null; abolishedOn?: string | null }) {
  if (status === "ABOLISHED") return <Badge tone="danger">폐지{abolishedOn ? ` · ${fmtDate(abolishedOn)}` : ""}</Badge>;
  if (status === "ABOLISHED_CANDIDATE") return <Badge tone="warning">폐지 후보</Badge>;
  return null;
}
