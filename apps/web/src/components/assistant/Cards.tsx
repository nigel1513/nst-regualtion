import Link from "next/link";
import { InstitutionMark } from "@/components/ui/institution-mark";
import type { Card } from "@/lib/chat";
import { fmtDate } from "@/lib/format";

function Snippet({ text, spans }: { text: string; spans: [number, number][] }) {
  const parts: React.ReactNode[] = [];
  let pos = 0;
  for (const [s, e] of [...spans].sort((a, b) => a[0] - b[0])) {
    if (s < pos || e > text.length) continue;
    if (s > pos) parts.push(text.slice(pos, s));
    parts.push(<mark key={s} className="rounded-xs bg-mark text-inherit">{text.slice(s, e)}</mark>);
    pos = e;
  }
  parts.push(text.slice(pos));
  return <>{parts}</>;
}

export function ArticleCard({ c }: { c: Card }) {
  return (
    <li className="rounded-md border border-border bg-bg-panel px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-small">
        <InstitutionMark code={c.institution.code} />
        <Link href={c.href} className="font-semibold text-fg hover:text-fg">{c.title} {c.label}</Link>
        {c.matched.length ? <span className="text-caption text-fg-muted">{c.matched.map((m) => m.label).join(" · ")}</span> : null}
        <span className="num ml-auto text-caption font-normal text-fg-muted">{c.institution.name ?? "법령"}{c.effective_from ? ` · ${fmtDate(c.effective_from)} 시행` : ""}</span>
      </div>
      <p className="mt-1.5 line-clamp-4 text-small text-fg"><Snippet text={c.snippet} spans={c.highlights} /></p>
    </li>
  );
}

/** 조문 카드: 기관이 여럿이고 많으면 기관별로 묶는다 (카드 안 카드 없이 머리 줄만). */
export function CardList({ cards, limit }: { cards: Card[]; limit?: number }) {
  const shown = limit ? cards.slice(0, limit) : cards;
  const insts = [...new Set(shown.map((c) => c.institution.code ?? ""))];
  if (insts.length > 2 && shown.length > 4) {
    return (
      <div className="flex flex-col gap-4">
        {insts.map((code) => {
          const g = shown.filter((c) => (c.institution.code ?? "") === code);
          return (
            <section key={code || "law"} aria-label={g[0].institution.name ?? "법령"}>
              <h4 className="mb-1.5 flex items-center gap-1.5 text-caption text-fg-muted">
                {g[0].institution.name ?? "법령"} <span className="num">{g.length}</span>
              </h4>
              <ul className="flex flex-col gap-2">{g.map((c) => <ArticleCard key={c.id} c={c} />)}</ul>
            </section>
          );
        })}
      </div>
    );
  }
  return <ul className="flex flex-col gap-2">{shown.map((c) => <ArticleCard key={c.id} c={c} />)}</ul>;
}
