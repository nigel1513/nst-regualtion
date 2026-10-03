import Link from "next/link";
import type { LawArticleDetail } from "@/lib/api";
import { workHref } from "@/lib/api";
import { REL_LABEL } from "@/lib/format";
import { lawHref } from "@/lib/law";

const INDENT: Record<string, string> = { paragraph: "", item: "pl-4", subitem: "pl-8" };
const MAX_CITING = 30;

export function LawPanel({ d, closeHref, showLawLink = true }: { d: LawArticleDetail; closeHref: string; showLawLink?: boolean }) {
  const a = d.article;
  const stale = d.law.status !== "현행" ? "폐지된 법령" : a.gone || a.deleted ? "현행 판본에서 삭제된 조문" : null;
  return (
    <section className="rounded-md border border-border bg-bg-panel p-4" aria-label="법령 조문">
      <div className="mb-2 flex items-start justify-between gap-2">
        <div>
          <div className="text-caption text-[var(--muted)]">{d.law.kind ?? "법령"}</div>
          <h2 className="text-long font-semibold">{d.law.name} {a.label}{a.heading ? `(${a.heading})` : ""}</h2>
        </div>
        <Link href={closeHref} scroll={false} className="shrink-0 text-caption" aria-label="법령 조문 패널 닫기">닫기</Link>
      </div>
      {d.version && <p className="mb-3 text-caption text-[var(--muted)]">{d.version.edition_line}</p>}
      {stale && <p className="mb-3"><span className="chip chip-amber">{stale}</span></p>}
      <div className="max-h-[50vh] overflow-auto text-body">
        {a.text && <p>{a.text}</p>}
        {d.children.map((c) => <p key={c.id} className={`mt-1 ${INDENT[c.unit] ?? ""}`}>{c.label} {c.text}</p>)}
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {d.links.article_go && <a className="btn" href={d.links.article_go} target="_blank" rel="noreferrer">law.go.kr에서 보기</a>}
        {showLawLink && <Link className="btn btn-dark" href={lawHref(d.law.law_id, `?a=${encodeURIComponent(a.path)}#${a.path}`)}>법령 화면</Link>}
      </div>
      <h3 className="mb-2 mt-4 text-small font-semibold">이 조문을 인용하는 내부규정 <span className="text-[var(--muted)]">{d.citing.length}</span></h3>
      {d.citing.length === 0 ? (
        <p className="text-small text-[var(--muted)]">인용하는 내부규정이 없습니다.</p>
      ) : (
        <ul className="flex flex-col gap-1.5 text-small">
          {d.citing.slice(0, MAX_CITING).map((c) => (
            <li key={`${c.work_id}#${c.path}`} className="flex items-start gap-2">
              <span className="chip shrink-0">{REL_LABEL[c.rel_type] ?? c.rel_type}</span>
              <Link href={workHref(c.work_id, `?a=${encodeURIComponent(c.path.split(".")[0])}#${c.path}`)}>
                {c.institution ? `${c.institution} · ` : ""}{c.work_title} {c.label}
              </Link>
            </li>
          ))}
        </ul>
      )}
      {d.citing.length > MAX_CITING && <p className="mt-1 text-caption text-[var(--muted)]">외 {d.citing.length - MAX_CITING}건</p>}
    </section>
  );
}
