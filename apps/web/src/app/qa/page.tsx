import { redirect } from "next/navigation";

/** 질의응답은 규정 도우미로 합쳐졌다 (§5). 질문은 그대로 넘긴다. */
export default async function QaPage({ searchParams }: { searchParams: Promise<{ q?: string }> }) {
  const { q } = await searchParams;
  redirect(typeof q === "string" && q ? `/assistant?${new URLSearchParams({ q })}` : "/assistant");
}
