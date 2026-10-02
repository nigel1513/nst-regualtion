// apps/web/src/components/RegAnnexCard.tsx
"use client";

import Link from "next/link";
import { type ReactNode, useEffect, useState } from "react";
import { type AnnexInfo, sourceHref } from "@/lib/api";

const TABLE_CSS = "[&_table]:border-collapse [&_td]:border [&_td]:border-[var(--line-strong)] [&_td]:px-1.5 [&_td]:py-1 "
  + "[&_th]:border [&_th]:border-[var(--line-strong)] [&_th]:bg-[#f3f5f8] [&_th]:px-1.5 [&_th]:py-1 text-[13px]";

/** 별표·별지: 원문 영역 이미지(클릭하면 크게), 원문 쪽으로 이동, 표 HTML(있으면), 추출 텍스트(접힘). */
export function RegAnnexCard({ workId, versionId, path, label, heading, children }: {
  workId: string; versionId: string; path: string; label: string; heading: string | null; children: ReactNode;
}) {
  const [info, setInfo] = useState<AnnexInfo | null | undefined>(undefined); // undefined: 불러오는 중, null: 이미지 없음
  const [open, setOpen] = useState(false);
  const [showTable, setShowTable] = useState(false);
  const [table, setTable] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    fetch(`/api/v1/annex?${new URLSearchParams({ version: versionId, path })}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((j: AnnexInfo | null) => { if (alive) setInfo(j); })
      .catch(() => { if (alive) setInfo(null); });
    return () => { alive = false; };
  }, [versionId, path]);

  useEffect(() => {
    if (!showTable || table !== null || !info?.table.url) return;
    fetch(info.table.url).then((r) => r.json()).then((j: { html: string }) => setTable(j.html)).catch(() => setTable(""));
  }, [showTable, table, info]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const jump = sourceHref(workId, `?${new URLSearchParams({ version: versionId, a: path })}`);
  const title = `${label}${heading ? ` ${heading}` : ""}`;
  return (
    <div className="mt-2 font-sans">
      {info === undefined && <p className="text-xs text-[var(--muted)]">원문 이미지를 불러오는 중…</p>}
      {info && (
        <figure className="overflow-hidden rounded-lg border border-[var(--line-strong)] bg-white">
          {showTable && table !== null ? (
            // 서버가 허용 목록(table·tr·td·th, colspan·rowspan)으로 정화한 HTML이다 (reg.core.annex_tables)
            <div className={`overflow-x-auto p-3 ${TABLE_CSS}`} dangerouslySetInnerHTML={{ __html: table }} />
          ) : (
            <button type="button" className="block w-full cursor-zoom-in" onClick={() => setOpen(true)} aria-label={`${title} 크게 보기`}>
              {/* eslint-disable-next-line @next/next/no-img-element -- API가 그린 PNG를 그대로 보여 준다 */}
              <img src={info.segments[0].url} alt={`${title} 원문 이미지`} loading="lazy" className="block w-full" />
            </button>
          )}
          <figcaption className="flex flex-wrap items-center gap-2 border-t border-[var(--line)] px-3 py-2 text-xs text-[var(--muted)]">
            <span>원문 {info.page}쪽{info.segments.length > 1 ? ` 외 ${info.segments.length - 1}조각` : ""}</span>
            {showTable && <span>표 변환: MinerU (자동 변환이라 원문 이미지와 다를 수 있음)</span>}
            <span className="ml-auto flex gap-2">
              {info.table.url && (
                <button type="button" className="btn h-8" onClick={() => setShowTable((s) => !s)}>{showTable ? "이미지로 보기" : "표로 보기"}</button>
              )}
              <Link className="btn h-8" href={jump}>원문 쪽으로 이동</Link>
            </span>
          </figcaption>
        </figure>
      )}
      <details className="mt-2 text-sm" open={info === null}>
        <summary className="cursor-pointer text-xs text-[var(--muted)]">추출 텍스트{info === null ? " (원문 이미지 없음)" : ""}</summary>
        <p className="mt-1 font-serif">{children}</p>
      </details>
      {open && info && (
        <div role="dialog" aria-modal="true" aria-label={`${title} 원문`} className="fixed inset-0 z-50 overflow-auto bg-black/80 p-4"
          onClick={() => setOpen(false)}>
          <div className="mx-auto flex max-w-5xl flex-col gap-3" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center gap-2 text-white">
              <span className="text-sm">{title}</span>
              <Link className="btn ml-auto h-8" href={jump}>원문 쪽으로 이동</Link>
              <button type="button" className="btn h-8" onClick={() => setOpen(false)}>닫기</button>
            </div>
            {info.segments.map((s) => (
              // eslint-disable-next-line @next/next/no-img-element -- API가 그린 PNG
              <img key={s.n} src={s.url} alt={`${title} ${s.page}쪽`} className="w-full bg-white" />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
