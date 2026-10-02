import { RefPopover } from "@/components/RefPopover";
import type { LawCite, Ref } from "@/lib/api";
import { REL_LABEL } from "@/lib/format";

export function ProvisionText({ text, refs, asOf, cites, lawHref }: {
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
    // 참조는 팝업으로 연다 (사용자 요청 2026-10-03: 보던 화면에서 다른 곳으로 옮기지 않게)
    if (cite && lawHref) {
      parts.push(<RefPopover key={i} target={{ kind: "law", articleId: cite.article_id as number }} tip={`${tip} · 조문 보기`}>{seg}</RefPopover>);
    } else if (r.resolution === "RESOLVED" && r.target_work_id && r.target_path) {
      parts.push(<RefPopover key={i} target={{ kind: "reg", workId: r.target_work_id, path: r.target_path, asOf }} tip={tip}>{seg}</RefPopover>);
    } else if (r.resolution === "RESOLVED" && r.target_work_id) {
      parts.push(<a key={i} href={`/regulations/${r.target_work_id.split("/").map(encodeURIComponent).join("/")}`} className="ref" title={tip}>{seg}</a>);
    } else {
      parts.push(<span key={i} className="ref-unresolved" title={`${tip} · 대상 미확인`}>{seg}</span>);
    }
    pos = r.end;
  }
  parts.push(text.slice(pos));
  return <>{parts}</>;
}
