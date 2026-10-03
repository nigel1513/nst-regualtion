import Link from "next/link";
import { notFound } from "next/navigation";
import { PdfPaneLazy as PdfPane } from "@/components/PdfPaneLazy";
import { apiGet, decodeSegments, validDate, type ViewData, workHref } from "@/lib/api";
import { fmtDate } from "@/lib/format";

export default async function SourcePage({ params, searchParams }: {
  params: Promise<{ id: string[] }>; searchParams: Promise<{ version?: string; a?: string; as_of?: string | string[] }>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  const a = typeof sp.a === "string" ? sp.a : undefined;
  const version = typeof sp.version === "string" ? sp.version : undefined;
  const as_of = validDate(sp.as_of);
  const workId = decodeSegments(id);
  const view = await apiGet<ViewData>("/api/v1/work/view", { id: workId, version, as_of });
  if (!view) notFound();
  const { work, version: v, provisions } = view;
  const arts = provisions.filter((p) => ["article", "supplement", "annex"].includes(p.unit));
  const sel = arts.find((p) => p.path === a) ?? arts.find((p) => p.anchor) ?? arts[0];
  const fileUrl = `/api/v1/file?version=${encodeURIComponent(v.id)}&kind=view`;
  const original = `/api/v1/file?version=${encodeURIComponent(v.id)}&kind=original`;
  return (
    <main className="pb-8">
      <div className="flex flex-wrap items-center gap-3 px-6 py-3.5">
        <Link className="btn" href={workHref(work.id, `?${new URLSearchParams({ ...(v.effective_from && v.version_state !== "CURRENT" ? { as_of: v.effective_from } : {}), ...(sel ? { a: sel.path } : {}) })}${sel ? `#${sel.path}` : ""}`)}>← 조문 보기</Link>
        <h1 className="text-[17px] font-bold">{work.title} · 원문 대조</h1>
        <span className="chip">{fmtDate(v.effective_from)} 시행본</span>
        <a className="text-[13px]" href={original}>원본 내려받기{v.source.file_name ? ` (${v.source.file_name})` : ""}</a>
      </div>
      <div className="grid grid-cols-1 gap-4 px-6 lg:grid-cols-[380px_minmax(0,1fr)]">
        <nav aria-label="조문 위치" className="card flex max-h-[calc(100vh-9rem)] flex-col gap-0.5 self-start overflow-auto p-2">
          {arts.map((p) => (
            <Link key={p.path} href={`?${new URLSearchParams({ a: p.path, ...(version ? { version } : {}), ...(as_of ? { as_of } : {}) })}`}
              className={`flex justify-between gap-2 rounded-lg px-3 py-2 text-[13px] text-[var(--ink-2)] hover:bg-bg-hover hover:no-underline ${p.path === sel?.path ? "bg-[var(--accent-soft)] text-[var(--accent)]" : ""}`}>
              <span><span className="font-medium">{p.label}</span> {p.heading}</span>
              <span className="text-[var(--muted)]">{p.anchor ? `${p.anchor.page}쪽` : "-"}</span>
            </Link>
          ))}
        </nav>
        {v.source.has_view && sel?.anchor ? (
          <PdfPane key={`${v.id}-${sel.path}`} fileUrl={fileUrl} page={sel.anchor.page} bbox={sel.anchor.bbox} label={v.source.file_name ?? v.title} />
        ) : v.source.has_view ? (
          <PdfPane key={v.id} fileUrl={fileUrl} page={1} bbox={null} label={v.source.file_name ?? v.title} />
        ) : (
          <div className="card p-6 text-sm">
            이 버전은 보기용 PDF가 없습니다({v.source.view_status === "failed" ? "변환 실패" : "준비 전"}). <a href={original}>원본 파일 내려받기</a>
          </div>
        )}
      </div>
    </main>
  );
}
