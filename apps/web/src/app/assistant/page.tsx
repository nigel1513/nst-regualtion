import { MessageSquare } from "lucide-react";
import Link from "next/link";
import { ComingSoon } from "@/components/ComingSoon";
import { buttonClass } from "@/components/ui/button";

/** 규정 도우미 (§5)는 다른 작업이 채운다. ⌘K·/search·/qa에서 넘어온 질문(q)은 보여 준다. */
export default async function AssistantPage({ searchParams }: { searchParams: Promise<{ q?: string }> }) {
  const { q } = await searchParams;
  const question = typeof q === "string" ? q.trim() : "";
  return (
    <ComingSoon title="규정 도우미" icon={MessageSquare}
      description={question ? `“${question}” — 검색과 질의응답을 합친 도우미를 만들고 있습니다.` : "검색과 질의응답을 합친 도우미를 만들고 있습니다."}>
      <Link href={question ? `/regulations?${new URLSearchParams({ q: question })}` : "/regulations"} className={buttonClass("secondary")}>규정 이름으로 찾기</Link>
    </ComingSoon>
  );
}
