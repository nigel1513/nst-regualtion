"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

const ACTIONS = [
  { status: "ACTION_REQUIRED", label: "조치 필요 · 개정 착수", cls: "btn border-[var(--accent)] bg-[var(--accent)] text-white" },
  { status: "NO_ACTION", label: "조치 불필요", cls: "btn" },
  { status: "ACKED", label: "확인함", cls: "btn" },
  { status: "RESOLVED", label: "반영 완료", cls: "btn" },
] as const;

export function AlertActions({ id }: { id: number }) {
  const router = useRouter();
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const act = async (status: string) => {
    if (status === "NO_ACTION" && !note.trim()) {
      setError("조치 불필요는 사유를 적어 주세요.");
      return;
    }
    setBusy(true);
    setError(null);
    const res = await fetch(`/api/v1/alerts/${id}/status`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status, ...(note.trim() ? { note: note.trim() } : {}) }) }).catch(() => null);
    setBusy(false);
    if (!res?.ok) {
      setError("처리하지 못했습니다. 잠시 후 다시 시도해 주세요.");
      return;
    }
    router.refresh();
  };
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor="note" className="text-caption font-semibold text-[var(--muted)]">검토 의견</label>
      <textarea id="note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} rows={3}
        className="rounded-md border border-[var(--line-strong)] bg-bg-panel p-2.5 text-body outline-none" placeholder="검토 내용이나 조치 불필요 사유" />
      <div className="flex flex-wrap gap-2">
        {ACTIONS.map((a) => <button key={a.status} type="button" disabled={busy} className={a.cls} onClick={() => void act(a.status)}>{a.label}</button>)}
      </div>
      {error && <p className="text-body text-[var(--red)]" role="alert">{error}</p>}
    </div>
  );
}
