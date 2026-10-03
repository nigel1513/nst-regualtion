"use client";

import { ArrowRight, ExternalLink, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import type { LawArticleDetail, ProvisionPopup } from "@/lib/api";
import { fmtDate } from "@/lib/format";

type Target =
  | { kind: "reg"; workId: string; path: string; asOf?: string }
  | { kind: "law"; articleId: number };

type View = {
  title: string; sub: string; heading: string;
  lines: { key: string; label: string; text: string; target: boolean }[];
  href: string | null; external: string | null;
};

function fromReg(d: ProvisionPopup): View {
  return {
    title: d.title, sub: [d.institution_name, d.effective_from ? `시행 ${fmtDate(d.effective_from)}` : null].filter(Boolean).join(" · "),
    heading: `${d.article.label}${d.article.heading ? `(${d.article.heading})` : ""}`,
    lines: d.lines.map((l) => ({ key: l.path, label: l.label, text: l.text, target: l.target })),
    href: d.href, external: null,
  };
}

function fromLaw(d: LawArticleDetail): View {
  const a = d.article;
  return {
    title: d.law.name, sub: d.version?.edition_line ?? "",
    heading: `${a.label}${a.heading ? `(${a.heading})` : ""}`,
    lines: [a, ...d.children].map((l) => ({ key: String(l.id), label: l === a ? "" : l.label, text: l.text, target: true })),
    href: `/laws/${encodeURIComponent(d.law.law_id)}`, external: d.links.article_go ?? d.links.law_go,
  };
}

/** 본문의 참조 문구: 누르면 페이지를 옮기지 않고 그 자리에 조문 팝업을 띄운다. 가리키는 항·호는 음영으로 표시한다. */
export function RefPopover({ target, tip, children }: { target: Target; tip: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<View | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pos, setPos] = useState<{ top: number; left: number }>({ top: 0, left: 0 });
  const box = useRef<HTMLDivElement>(null);
  const btn = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); btn.current?.focus(); } };
    const onDown = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node) && !btn.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    return () => { document.removeEventListener("keydown", onKey); document.removeEventListener("mousedown", onDown); };
  }, [open]);

  const show = async () => {
    const r = btn.current?.getBoundingClientRect();
    if (r) {
      const width = Math.min(560, window.innerWidth - 32);
      setPos({ top: Math.min(r.bottom + 8, window.innerHeight - 120), left: Math.max(16, Math.min(r.left, window.innerWidth - width - 16)) });
    }
    setOpen((o) => !o);
    if (view || open) return;
    try {
      const url = target.kind === "reg"
        ? `/api/v1/provision?${new URLSearchParams({ work: target.workId, path: target.path, ...(target.asOf ? { as_of: target.asOf } : {}) })}`
        : `/api/v1/law/article/${target.articleId}`;
      const res = await fetch(url);
      if (!res.ok) throw new Error(res.status === 404 ? "참조된 조문을 찾지 못했습니다" : "조문을 불러오지 못했습니다");
      const d = await res.json();
      setView(target.kind === "reg" ? fromReg(d as ProvisionPopup) : fromLaw(d as LawArticleDetail));
    } catch (e) {
      setError(e instanceof Error ? e.message : "조문을 불러오지 못했습니다");
    }
  };

  return (
    <>
      <button ref={btn} type="button" className="ref" title={tip} aria-expanded={open} aria-haspopup="dialog" onClick={() => void show()}>
        {children}
      </button>
      {open && (
        <div ref={box} role="dialog" aria-label={view?.heading ?? "참조 조문"}
          className="fixed z-[var(--z-popover)] flex max-h-[60vh] w-[min(560px,calc(100vw-32px))] flex-col overflow-hidden rounded-md border border-border bg-bg-panel text-left shadow-popover"
          style={{ top: pos.top, left: pos.left }}>
          <div className="flex items-start justify-between gap-3 border-b border-border-subtle px-4 py-3">
            <div className="min-w-0">
              <p className="truncate text-body font-semibold text-fg">{view ? `${view.title} ${view.heading}` : "불러오는 중…"}</p>
              {view?.sub && <p className="truncate text-caption text-fg-muted">{view.sub}</p>}
            </div>
            <button type="button" className="press inline-flex size-7 shrink-0 cursor-pointer items-center justify-center rounded-sm text-fg-muted hover:bg-bg-hover hover:text-fg" aria-label="닫기" onClick={() => setOpen(false)}><X aria-hidden="true" className="size-4" strokeWidth={1.75} /></button>
          </div>
          <div className="overflow-y-auto px-4 py-3 text-long text-fg">
            {error && <p className="text-small text-danger">{error}</p>}
            {view?.lines.map((l) => (
              <p key={l.key} className={`mb-1 rounded-sm px-1.5 py-0.5 ${l.target ? "bg-mark" : ""}`}>
                {l.label && <span className="mr-1 font-semibold">{l.label}</span>}{l.text}
              </p>
            ))}
          </div>
          {view && (
            <div className="flex gap-4 border-t border-border-subtle px-4 py-2 text-small">
              {view.href && <Link href={view.href} className="inline-flex items-center gap-1">이 규정 열기<ArrowRight aria-hidden="true" className="size-3.5" strokeWidth={1.75} /></Link>}
              {view.external && <a href={view.external} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1">law.go.kr에서 보기<ExternalLink aria-hidden="true" className="size-3.5" strokeWidth={1.75} /></a>}
            </div>
          )}
        </div>
      )}
    </>
  );
}
