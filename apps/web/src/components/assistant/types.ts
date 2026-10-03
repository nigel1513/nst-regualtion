import type { AnswerData, Card, Citation, DoneData, Stage, TableData } from "@/lib/chat";

/** 대화의 한 차례: 질문과, 이벤트로 채워지는 답. */
export type Turn = {
  id: string; question: string; stage?: Stage; stageLabel?: string; intent?: string; scopeNote?: string;
  cards: Card[]; delta: string; answer?: AnswerData; table?: TableData; citations: Citation[]; followups: string[];
  done?: DoneData; error?: { status: number; message: string }; stopped?: boolean;
};

export type SavedChat = { id: string; title: string; at: number; turns: Turn[]; scope?: unknown };

export const CHATS_KEY = "nst-reg-chats";

export function newTurn(question: string): Turn {
  return { id: Math.random().toString(36).slice(2, 10), question, cards: [], delta: "", citations: [], followups: [] };
}

/** 다음 질문에 붙여 보낼 앞선 대화 (답은 짧게): 최대 5차례 + 이번 질문 = 메시지 ≤ 11. */
export function history(turns: Turn[]): { role: "user" | "assistant"; content: string }[] {
  const out: { role: "user" | "assistant"; content: string }[] = [];
  for (const t of turns.filter((x) => x.done && !x.error).slice(-5)) {
    const reply = t.answer?.explanation || t.answer?.sentences.map((s) => s.text).join(" ")
      || (t.table ? `${t.table.item}: ${t.table.rows.filter((r) => r.value).map((r) => `${r.institution.name} ${r.value}`).join(", ")}` : "")
      || t.cards.slice(0, 3).map((c) => `${c.title ?? ""} ${c.label ?? ""}`).join(", ");
    out.push({ role: "user", content: t.question.slice(0, 2000) });
    if (reply) out.push({ role: "assistant", content: reply.slice(0, 2000) });
  }
  return out;
}
