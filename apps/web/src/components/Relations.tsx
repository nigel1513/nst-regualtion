"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { workHref } from "@/lib/api";
import { REL_LABEL } from "@/lib/format";

type Out = { evidence_text: string; rel_type: string; target_work_id: string | null; target_path: string | null;
  target_name: string | null; target_title: string | null; resolution: string };
type In = { evidence_text: string; rel_type: string; source_work_id: string; source_title: string; source_path: string;
  source_label: string };

const CHIP: Record<string, string> = { EXCEPTION: "chip-amber", MUTATIS: "chip-blue", BASIS: "chip-blue", DELEGATION: "chip-blue" };

export function Relations({ pvId, label, workId }: { pvId: number; label: string; workId: string }) {
  const [data, setData] = useState<{ outgoing: Out[]; incoming: In[] } | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let alive = true;
    setData(null);
    fetch(`/api/v1/references?pv=${pvId}`).then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => alive && setData(d)).catch(() => alive && setError(true));
    return () => { alive = false; };
  }, [pvId]);
  return (
    <section className="card p-4" aria-live="polite">
      <h2 className="mb-3 text-[13px] font-semibold">{label}의 관계</h2>
      {error && <p className="text-[13px] text-[var(--muted)]">관계를 불러오지 못했습니다.</p>}
      {!data && !error && <p className="text-[13px] text-[var(--muted)]">불러오는 중…</p>}
      {data && data.outgoing.length + data.incoming.length === 0 && <p className="text-[13px] text-[var(--muted)]">연결된 조항이 없습니다.</p>}
      {data && (
        <ul className="flex flex-col gap-2.5 text-[13px]">
          {data.outgoing.map((r, i) => (
            <li key={`o${i}`} className="flex items-start gap-2.5">
              <span className={`chip shrink-0 ${CHIP[r.rel_type] ?? ""}`}>{REL_LABEL[r.rel_type] ?? r.rel_type}</span>
              <div>
                {r.target_work_id ? (
                  <Link href={r.target_work_id === workId ? `#${r.target_path ?? ""}` : workHref(r.target_work_id, r.target_path ? `#${r.target_path}` : "")}>
                    {r.target_work_id === workId ? r.evidence_text : `${r.target_title ?? r.target_name} ${r.target_path ?? ""}`}
                  </Link>
                ) : (
                  <span>{r.target_name ?? r.evidence_text}</span>
                )}
                {r.resolution !== "RESOLVED" && <div className="text-xs text-[var(--amber)]">대상 미해석 · 검수 대기</div>}
              </div>
            </li>
          ))}
          {data.incoming.map((r, i) => (
            <li key={`i${i}`} className="flex items-start gap-2.5">
              <span className="chip shrink-0">이 조항을 {REL_LABEL[r.rel_type] ?? r.rel_type}</span>
              <Link href={r.source_work_id === workId ? `#${r.source_path}` : workHref(r.source_work_id, `#${r.source_path}`)}>
                {r.source_work_id === workId ? r.source_path : `${r.source_title} ${r.source_path}`}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
