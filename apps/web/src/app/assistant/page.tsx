import { Assistant } from "@/components/assistant/Assistant";
import { apiGet, type Institution } from "@/lib/api";
import type { Scope, TopicOption } from "@/lib/chat";

type SP = { q?: string; inst?: string | string[]; work?: string; topic?: string };

/**
 * 규정 도우미 (서비스 UI 개편 §5). ?q=는 바로 보낸다(⌘K·/search·/qa). ?inst=로 기관 범위,
 * ?work=로 규정 하나(규정 보기의 "이 규정에 묻기": 그 기관 + work_ids=[그 규정]), ?topic=으로 주제.
 */
export default async function AssistantPage({ searchParams }: { searchParams: Promise<SP> }) {
  const sp = await searchParams;
  const [instRows, topicRows] = await Promise.all([
    apiGet<Institution[]>("/api/v1/institutions").catch(() => null),
    apiGet<TopicOption[]>("/api/v1/topics").catch(() => null),
  ]);
  const insts = (instRows ?? []).map((i) => ({ code: i.code, name: i.name, works: i.works }));
  const topics = (topicRows ?? []).map((t) => ({ id: t.id, label: t.label, works: t.works }));
  const q = typeof sp.q === "string" ? sp.q.trim().slice(0, 2000) : "";
  const instList = (Array.isArray(sp.inst) ? sp.inst : sp.inst ? sp.inst.split(",") : []).filter((c) => insts.some((i) => i.code === c));
  const work = typeof sp.work === "string" && sp.work.startsWith("kr/") ? sp.work : null;
  const topic = typeof sp.topic === "string" && topics.some((t) => t.id === sp.topic) ? sp.topic : undefined;
  // 규정 id는 kr/reg/{기관}/{규정명}: 범위 칩에 보일 이름은 끝 조각, 기관은 셋째 조각
  const parts = work?.split("/") ?? [];
  const works = work ? [{ id: work, title: work.startsWith("kr/reg/") ? parts.slice(3).join("/") : "이 법령", institution: work.startsWith("kr/reg/") ? parts[2] : null }] : [];
  const scope: Scope = { mode: instList.length ? "institutions" : "all", institutions: instList, work_ids: work ? [work] : [], works, ...(topic ? { topic } : {}) };
  return <Assistant key={`${q}|${instList.join(",")}|${work ?? ""}|${topic ?? ""}`} insts={insts} topics={topics} initialQ={q} initialScope={scope} />;
}
