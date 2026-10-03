import Link from "next/link";
import type { LawAnnex } from "@/lib/api";
import { annexNo } from "@/lib/law";

export function AnnexList({ annexes, hrefFor }: { annexes: LawAnnex[]; hrefFor: (seq: string) => string }) {
  return (
    <section className="card p-4" aria-label="별표·서식">
      <h2 className="mb-3 text-small font-semibold">별표·서식 <span className="text-[var(--muted)]">{annexes.length}</span></h2>
      {annexes.length === 0 ? (
        <p className="text-small text-[var(--muted)]">별표·서식이 없습니다.</p>
      ) : (
        <ul className="flex flex-col gap-2.5 text-small">
          {annexes.map((x) => (
            <li key={x.seq} className="flex flex-col gap-1">
              <div><span className="chip mr-1.5">{x.kind ?? "별표"} {annexNo(x.number)}</span>{x.title}</div>
              <div className="flex flex-wrap gap-3 text-caption">
                {(x.has_pdf || x.has_html) && <Link href={hrefFor(x.seq)} scroll={false}>바로 보기</Link>}
                <a href={x.view_url} target="_blank" rel="noreferrer">law.go.kr</a>
                {x.file_url && <a href={x.file_url} target="_blank" rel="noreferrer">원본 파일</a>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
