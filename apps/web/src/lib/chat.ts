/** 규정 도우미 이벤트 계약 (POST /api/v1/chat, SSE). 백엔드 src/reg/qa/chat.py와 맞춘다. */
export type ChatInst = { code: string | null; name: string | null };
export type Card = {
  id: string; institution: ChatInst; work_id: string; version_id: string; title: string | null; article_path: string;
  label: string | null; matched: { path: string; label: string }[]; snippet: string; highlights: [number, number][];
  effective_from: string | null; kind: "reg" | "law" | "admrul" | null; href: string; score: number | null;
};
export type Citation = {
  n: number; institution: ChatInst; work_id: string; version_id: string; title: string | null; path: string; label: string;
  quote: string; href: string;
};
export type Stage = "understand" | "search" | "read" | "write" | "compare";
export type Conclusion = "미충족" | "충족" | "조건부" | "판단불가" | null;
export type AnswerData = {
  conclusion: Conclusion; sentences: { text: string; cites: number[] }[]; explanation: string; checks: string[];
  contact: string | null; based_on?: ChatInst[];
};
export type TableData = {
  item: string; topic?: string; item_id?: string; unit?: string; source: "compare_cell" | "extracted"; focus: string | null;
  rows: { institution: ChatInst; value: string | null; value_norm?: string; absent?: boolean; cite: number | null; title?: string; href?: string }[];
};
export type DoneData = {
  conversation_id: string; qa_id: number | null; intent: string | null;
  status: "answered" | "evidence_only" | "not_found" | "lookup" | "compared" | "error"; note: string | null;
  first_results_ms: number | null; latency_ms: number;
};
export type StatusData = {
  stage: Stage; label: string; conversation_id?: string; intent?: "lookup" | "question" | "comparison"; query?: string;
  rewritten?: boolean; institutions?: ChatInst[]; scope_mode?: "all" | "institutions"; work_ids?: string[]; topic?: string | null;
};
export type ChatEvent =
  | { event: "status"; data: StatusData }
  | { event: "results"; data: { cards: Card[] } }
  | { event: "answer_delta"; data: { text: string } }
  | { event: "answer"; data: AnswerData }
  | { event: "table"; data: TableData }
  | { event: "citations"; data: { items: Citation[] } }
  | { event: "followups"; data: { items: string[] } }
  | { event: "done"; data: DoneData };

/** 고른 규정 (범위 칩 표시용: 이름·기관). 서버에는 work_ids만 간다. */
export type ScopeWork = { id: string; title: string; institution: string | null };
export type Scope = { mode: "all" | "institutions"; institutions: string[]; work_ids: string[]; topic?: string; works?: ScopeWork[] };
export type TopicOption = { id: string; label: string; works: number };

/** 서버로 보낼 범위: 표시용 works는 빼고, 주제가 없으면 키도 뺀다. */
export function requestScope(s: Scope): Omit<Scope, "works"> {
  return { mode: s.mode, institutions: s.institutions, work_ids: s.work_ids, ...(s.topic ? { topic: s.topic } : {}) };
}
export type ChatRequest = {
  messages: { role: "user" | "assistant"; content: string }[]; scope: Omit<Scope, "works">; as_of?: string; conversation_id?: string;
};

export class ChatHttpError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

/** SSE를 읽어 이벤트마다 onEvent를 부른다. "event: x\ndata: {json}\n\n" 덩어리. signal로 멈춘다. */
export async function streamChat(body: ChatRequest, onEvent: (e: ChatEvent) => void, signal: AbortSignal): Promise<void> {
  const res = await fetch("/api/v1/chat", {
    method: "POST", headers: { "content-type": "application/json", accept: "text/event-stream" }, body: JSON.stringify(body), signal,
  });
  if (!res.ok || !res.body) {
    let detail = "";
    try { detail = ((await res.json()) as { detail?: string }).detail ?? ""; } catch { /* 본문 없음 */ }
    throw new ChatHttpError(res.status, detail);
  }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i: number;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, i);
      buf = buf.slice(i + 2);
      let ev = "", data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) ev = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (ev && data) {
        try { onEvent({ event: ev, data: JSON.parse(data) } as ChatEvent); } catch { /* 깨진 덩어리는 건너뛴다 */ }
      }
    }
  }
}
