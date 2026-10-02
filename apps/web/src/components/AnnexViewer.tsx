import Link from "next/link";
import type { LawAnnex } from "@/lib/api";

/** 저장된 별표: PDF가 있으면 PDF, 없으면 스크립트를 지운 HTML을 sandbox iframe에 (판정 R5). */
export function AnnexViewer({ annex, closeHref }: { annex: LawAnnex; closeHref: string }) {
  const frame = "h-[70vh] w-full rounded-lg border border-[var(--line)] bg-white";
  return (
    <section className="card p-4" aria-label="별표 보기">
      <div className="mb-2 flex items-start justify-between gap-2">
        <h2 className="text-[13px] font-semibold">{annex.title}</h2>
        <Link href={closeHref} scroll={false} className="shrink-0 text-xs" aria-label="별표 보기 닫기">닫기</Link>
      </div>
      {annex.has_pdf ? (
        <iframe title={annex.title} src={`/api/v1/law/annex/${annex.seq}/pdf`} className={frame} />
      ) : (
        <iframe title={annex.title} src={`/api/v1/law/annex/${annex.seq}/html`} sandbox="" referrerPolicy="no-referrer" className={frame} />
      )}
      <p className="mt-2 text-xs text-[var(--muted)]">
        표시되지 않으면 <a href={annex.view_url} target="_blank" rel="noreferrer">law.go.kr에서 보기</a>
      </p>
    </section>
  );
}
