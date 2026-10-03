import { Columns3 } from "lucide-react";
import Link from "next/link";
import { redirect } from "next/navigation";
import { ComingSoon } from "@/components/ComingSoon";
import { buttonClass } from "@/components/ui/button";
import { workHref } from "@/lib/api";

/** 기관 비교 (§4)는 다른 작업이 채운다. 옛 판본 비교 주소(?work=)는 규정 보기의 개정 이력 탭으로 보낸다. */
export default async function ComparePage({ searchParams }: { searchParams: Promise<{ work?: string; from?: string; to?: string }> }) {
  const { work, from, to } = await searchParams;
  if (typeof work === "string" && work) {
    redirect(workHref(work, `?${new URLSearchParams({ tab: "history", ...(from ? { from } : {}), ...(to ? { to } : {}) })}`));
  }
  return (
    <ComingSoon title="기관 비교" icon={Columns3} description="같은 주제의 규정을 기관별 항목 표로 비교하는 화면을 만들고 있습니다.">
      <Link href="/regulations" className={buttonClass("secondary")}>규정 찾기로</Link>
    </ComingSoon>
  );
}
