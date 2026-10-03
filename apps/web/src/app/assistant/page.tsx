import { Assistant } from "@/components/assistant/Assistant";
import { apiGet, type Institution } from "@/lib/api";
import type { Scope } from "@/lib/chat";

type SP = { q?: string; inst?: string | string[]; work?: string };

/**
 * 규정 도우미 (서비스 UI 개편 §5). ?q=는 바로 보낸다(⌘K·/search·/qa). ?inst=로 기관 범위,
 * ?work=로 규정 하나(규정 보기의 "이 규정에 묻기": 그 기관 + work_ids=[그 규정]).
 */
export default async function AssistantPage({ searchParams }: { searchParams: Promise<SP> }) {
  const sp = await searchParams;
  const insts = ((await apiGet<Institution[]>("/api/v1/institutions").catch(() => null)) ?? []).map((i) => ({ code: i.code, name: i.name, works: i.works }));
  const q = typeof sp.q === "string" ? sp.q.trim().slice(0, 2000) : "";
  const instList = (Array.isArray(sp.inst) ? sp.inst : sp.inst ? sp.inst.split(",") : []).filter((c) => insts.some((i) => i.code === c));
  const work = typeof sp.work === "string" && sp.work.startsWith("kr/") ? sp.work : null;
  const scope: Scope = { mode: instList.length ? "institutions" : "all", institutions: instList, work_ids: work ? [work] : [] };
  // 규정 id는 kr/reg/{기관}/{규정명}: 범위 단추에 보일 이름은 끝 조각
  const workTitle = work ? (work.startsWith("kr/reg/") ? work.split("/").slice(3).join("/") : "이 법령") : null;
  return <Assistant key={`${q}|${instList.join(",")}|${work ?? ""}`} insts={insts} initialQ={q} initialScope={scope} workTitle={workTitle} />;
}
