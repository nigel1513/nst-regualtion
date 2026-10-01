"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import type { QaEvidence, QaResult } from "@/lib/api";
import { workHref } from "@/lib/api";
import { fmtDate, REL_LABEL } from "@/lib/format";

type Turn = { id: number; question: string; result?: QaResult; error?: string; pending?: boolean };
type Inst = { code: string; name: string };

const VERDICT_CHIP: Record<string, string> = { 미충족: "chip-red", 조건부: "chip-amber", 충족: "chip-green", 판단불가: "" };

function highlight(text: string, quotes: string[]): React.ReactNode {
  const norm = (s: string) => s.replace(/\s+/g, "");
  for (const q of quotes) {
    const nq = norm(q);
    if (!nq) continue;
    // 공백을 무시하고 위치를 찾은 뒤 원문 좌표로 되돌린다
    const map: number[] = [];
    let flat = "";
    for (let i = 0; i < text.length; i++) if (!/\s/.test(text[i])) { map.push(i); flat += text[i]; }
    const at = flat.indexOf(nq);
    if (at < 0) continue;
    const s = map[at], e = map[at + nq.length - 1] + 1;
    return <>{text.slice(0, s)}<mark className="rounded bg-[var(--mark)] px-0.5">{text.slice(s, e)}</mark>{text.slice(e)}</>;
  }
  return text;
}

function EvidenceCard({ e, quotes, cited }: { e: QaEvidence; quotes: string[]; cited: boolean }) {
  const art = e.path.split(".")[0];
  return (
    <div className={`rounded-[10px] border px-3.5 py-3 ${cited ? "border-[var(--accent-line)] bg-[#f5f8fe]" : "border-[var(--line)] bg-white"}`}>
      <div className="flex justify-between gap-2 text-[13px]">
        <span className="font-semibold">{e.title} {e.label}</span>
        <Link href={workHref(e.work_id, `?${new URLSearchParams({ a: art })}#${encodeURIComponent(art)}`)}>원문</Link>
      </div>
      <p className="mt-1.5 line-clamp-6 whitespace-pre-line font-serif text-sm leading-[1.7]">{highlight(e.text.slice(0, 600), quotes)}</p>
      <div className="mt-1.5 text-xs text-[var(--muted)]">
        {e.id} · {fmtDate(e.effective_from)} 시행본{e.rel ? ` · ${REL_LABEL[e.rel] ?? e.rel}` : ""}{e.role === "exception" ? " · 예외 조항" : ""}
      </div>
    </div>
  );
}

function ResultView({ r, institutions, onPick }: { r: QaResult; institutions: Inst[]; onPick: (code: string) => void }) {
  const [fb, setFb] = useState<string | null>(null);
  const instName = institutions.find((i) => i.code === r.institution)?.name ?? r.institution;
  if (r.status === "need_institution") {
    return (
      <div className="max-w-[80%] self-start rounded-[14px_14px_14px_4px] border border-[var(--line)] bg-white px-4 py-3.5 text-sm">
        <p>{r.note}</p>
        <div className="mt-2.5 flex flex-wrap gap-2">
          {(r.options ?? institutions).map((o) => <button key={o.code} className="btn" onClick={() => onPick(o.code)}>{o.name}</button>)}
        </div>
      </div>
    );
  }
  const quotes = r.answer?.근거.map((c) => c.인용) ?? [];
  const cited = new Set(r.answer?.근거.map((c) => c.id) ?? []);
  const shown = r.evidence.filter((e) => e.role !== "exception" || cited.has(e.id)).slice(0, 4);
  const send = async (v: "helpful" | "not_helpful") => {
    setFb(v);
    await fetch(`/api/v1/qa/${r.id}/feedback`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ feedback: v }) }).catch(() => null);
  };
  return (
    <section className="card flex flex-col gap-4 p-5">
      <div className="flex flex-wrap items-center gap-2">
        {instName && <span className="chip">기관 {instName}</span>}
        <span className="chip">기준일 {r.as_of ? fmtDate(r.as_of) : "현행"}</span>
      </div>
      {shown.length > 0 && (
        <div>
          <div className="mb-2 text-xs font-semibold text-[var(--muted)]">근거 조문</div>
          <div className="grid grid-cols-1 gap-2.5 md:grid-cols-2">
            {shown.map((e) => <EvidenceCard key={e.id} e={e} quotes={quotes} cited={cited.has(e.id)} />)}
          </div>
        </div>
      )}
      {r.answer ? (
        <div className="flex flex-col gap-3 border-t border-[#ebeef2] pt-4">
          <div className="flex items-center gap-2.5">
            <span className={`chip h-7 px-3 text-[13px] font-bold ${VERDICT_CHIP[r.answer.결론] ?? ""}`}>{r.answer.결론}</span>
            {r.verdict_source === "code" && <span className="text-xs text-[var(--muted)]">기한은 원문 숫자로 계산했습니다</span>}
          </div>
          <p className="text-[15px] leading-[1.75]">{r.answer.설명}</p>
          {r.answer.확인_필요.length > 0 && (
            <div className="rounded-[10px] bg-[var(--amber-soft)] px-3.5 py-3 text-sm leading-[1.7]">
              <div className="mb-1 font-semibold text-[#7a3a00]">확인이 필요한 점</div>
              {r.answer.확인_필요.map((x, i) => <div key={i}>· {x}</div>)}
            </div>
          )}
          <div className="flex flex-wrap items-center justify-between gap-3 text-[13px] text-[var(--muted)]">
            <span>문의처: {r.answer.문의처 || "소관부서"} · 법적 판단이 아니며 소관부서 확인이 필요합니다.</span>
            <span className="flex gap-1.5">
              <button className="btn" disabled={!!fb} onClick={() => send("helpful")}>{fb === "helpful" ? "고맙습니다" : "도움됨"}</button>
              <button className="btn" disabled={!!fb} onClick={() => send("not_helpful")}>{fb === "not_helpful" ? "의견 반영할게요" : "아니요"}</button>
            </span>
          </div>
        </div>
      ) : (
        <p className="rounded-[10px] bg-[#f7f8fa] px-3.5 py-3 text-sm">{r.note ?? "근거 조문만 보여드립니다."}</p>
      )}
      {r.verification && r.answer && (
        <details className="text-[13px]">
          <summary className="cursor-pointer text-[var(--muted)]">답변 검증</summary>
          <ul className="mt-2 grid grid-cols-2 gap-1">
            <li>인용 조문 존재: {r.verification.citations_exist ? "통과" : "실패"}</li>
            <li>인용 문구 원문 일치: {r.verification.quotes_match ? "통과" : "실패"}</li>
            <li>숫자 일치: {r.verification.numbers_match ? "통과" : "실패"}</li>
            <li>판정: {r.verdict_source === "code" ? "코드 계산" : "LLM"}</li>
          </ul>
        </details>
      )}
    </section>
  );
}

export function QaChat({ institutions }: { institutions: Inst[] }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState("");
  const [inst, setInst] = useState<string | null>(null);

  const nextId = useRef(0);
  // 응답은 순서가 뒤바뀌어 올 수 있어 마지막 칸이 아니라 질문마다 붙인 id로 채운다.
  // 기관을 골라 다시 물을 때(replace)는 되묻기 칸을 그 자리에서 답으로 바꾼다.
  const ask = async (question: string, institution: string | null, replace?: number) => {
    const id = replace ?? nextId.current++;
    const fill = (patch: Omit<Turn, "id" | "question">) =>
      setTurns((t) => t.map((x) => x.id === id ? { id, question, ...patch } : x));
    setTurns((t) => replace === undefined ? [...t, { id, question, pending: true }] : t.map((x) => x.id === id ? { id, question, pending: true } : x));
    try {
      const res = await fetch("/api/v1/qa", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, ...(institution ? { institution } : {}) }) });
      const body = await res.json().catch(() => ({}));
      fill(res.ok ? { result: body as QaResult } : { error: body.detail ?? "오류가 발생했습니다" });
    } catch {
      fill({ error: "서버에 연결하지 못했습니다" });
    }
  };
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const q = text.trim();
    if (q.length < 2) return;
    setText("");
    void ask(q, inst);
  };
  return (
    <div className="flex flex-col gap-4">
      {turns.map((t) => (
        <div key={t.id} className="flex flex-col gap-3">
          <div className="max-w-[78%] self-end rounded-[14px_14px_4px_14px] bg-[var(--ink)] px-4 py-3 text-[15px] leading-relaxed text-white">{t.question}</div>
          {t.pending && <p className="text-sm text-[var(--muted)]" aria-live="polite">근거를 찾고 있습니다…</p>}
          {t.error && <p className="text-sm text-[var(--red)]">{t.error}</p>}
          {t.result && <ResultView r={t.result} institutions={institutions} onPick={(code) => { setInst(code); void ask(t.question, code, t.id); }} />}
        </div>
      ))}
      <form onSubmit={submit} className="flex gap-2 rounded-[14px] border border-[var(--line-strong)] bg-white p-2">
        <label htmlFor="qa" className="sr-only">질문</label>
        <input id="qa" value={text} onChange={(e) => setText(e.target.value)} maxLength={500}
          placeholder="규정에 대해 질문하세요 · 개인정보는 입력하지 마세요" className="min-w-0 grow border-0 px-2.5 text-[15px] outline-none" />
        {inst && <button type="button" className="chip" onClick={() => setInst(null)} title="기관 선택 해제">{institutions.find((x) => x.code === inst)?.name} ×</button>}
        <button className="btn border-[var(--accent)] bg-[var(--accent)] text-white" type="submit">보내기</button>
      </form>
    </div>
  );
}
