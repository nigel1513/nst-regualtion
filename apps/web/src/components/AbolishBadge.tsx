import { fmtDate } from "@/lib/format";

export const ABOLISH_TASK_LABEL: Record<string, string> = { ABOLISHED: "폐지 확인" };

/** 폐지(확정)는 빨강, 폐지 후보(ALIO 목록에서 3일 연속 사라짐, 사람 확인 대기)는 주황. 현행이면 아무것도 그리지 않는다. */
export function AbolishBadge({ status, abolishedOn }: { status?: string | null; abolishedOn?: string | null }) {
  if (status === "ABOLISHED") return <span className="chip chip-red">폐지{abolishedOn ? ` · ${fmtDate(abolishedOn)}` : ""}</span>;
  if (status === "ABOLISHED_CANDIDATE") return <span className="chip chip-amber">폐지 후보</span>;
  return null;
}
