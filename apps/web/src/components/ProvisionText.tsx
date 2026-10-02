import Link from "next/link";
import type { LawCite, Ref } from "@/lib/api";
import { workHref } from "@/lib/api";
import { REL_LABEL } from "@/lib/format";

export function ProvisionText({ text, refs, workId, asOf, cites, lawHref }: {
  text: string; refs?: Ref[]; workId: string; asOf?: string; cites?: LawCite[]; lawHref?: (articleId: number) => string;
}) {
  if (!refs?.length) return <>{text}</>;
  const parts: React.ReactNode[] = [];
  let pos = 0;
  for (const [i, r] of refs.entries()) {
    if (r.start < pos || r.end > text.length) continue;
    parts.push(text.slice(pos, r.start));
    const seg = text.slice(r.start, r.end);
    const tip = `${REL_LABEL[r.rel_type] ?? r.rel_type}${r.target_name ? ` · ${r.target_name}` : ""}`;
    const cite = cites?.find((c) => c.start === r.start && c.article_id != null);
    if (cite && lawHref) {
      parts.push(<Link key={i} href={lawHref(cite.article_id as number)} scroll={false} className="ref" title={`${tip} · 조문 보기`}>{seg}</Link>);
    } else if (r.resolution === "RESOLVED" && r.target_work_id) {
      const hash = r.target_path ? `#${r.target_path}` : "";
      const href = r.target_work_id === workId
        ? `?${new URLSearchParams({ ...(asOf ? { as_of: asOf } : {}), a: (r.target_path ?? "").split(".")[0] })}${hash}`
        : workHref(r.target_work_id, hash);
      parts.push(<Link key={i} href={href} className="ref" title={tip}>{seg}</Link>);
    } else {
      parts.push(<span key={i} className="ref-unresolved" title={`${tip} · 대상 미확인`}>{seg}</span>);
    }
    pos = r.end;
  }
  parts.push(text.slice(pos));
  return <>{parts}</>;
}
