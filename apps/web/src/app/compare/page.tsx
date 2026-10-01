import Link from "next/link";
import { apiGet, type DiffData, type VersionRow, workHref } from "@/lib/api";
import { CHANGE_LABEL, fmtDate } from "@/lib/format";

export default async function ComparePage({ searchParams }: { searchParams: Promise<{ work?: string; from?: string; to?: string }> }) {
  const { work, from, to } = await searchParams;
  if (!work) return <main className="mx-auto max-w-3xl px-6 py-10"><p className="card p-6">비교할 규정을 먼저 고르세요. <Link href="/regulations">규정 목록</Link></p></main>;
  const versions = (await apiGet<VersionRow[]>("/api/v1/work/versions", { id: work })) ?? [];
  const toId = to ?? versions[0]?.id;
  const fromId = from ?? versions[1]?.id;
  const diff = fromId && toId ? await apiGet<DiffData>("/api/v1/diff", { from: fromId, to: toId }) : null;
  const sel = (name: string, value: string | undefined) => (
    <select name={name} defaultValue={value} className="h-9 rounded-lg border border-[var(--line-strong)] bg-white px-2 text-[13px]">
      {versions.map((v) => <option key={v.id} value={v.id}>{fmtDate(v.effective_from)} 시행{v.amendment_no ? ` · 제${v.amendment_no}호` : ""}</option>)}
    </select>
  );
  return (
    <main className="px-6 py-4">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Link className="btn" href={workHref(work)}>← 조문 보기</Link>
        <h1 className="text-[17px] font-bold">연혁과 신구 비교</h1>
      </div>
      {versions.length < 2 ? <p className="card p-6 text-sm">비교할 버전이 하나뿐입니다.</p> : (
        <>
          <form className="card mb-4 flex flex-wrap items-center gap-2 px-4 py-3 text-[13px]">
            <input type="hidden" name="work" value={work} />
            <label>구 {sel("from", fromId)}</label><span>→</span><label>신 {sel("to", toId)}</label>
            <button className="btn btn-dark" type="submit">비교</button>
            {diff && <span className="ml-auto text-[var(--muted)]">변경 {diff.changes.length}건</span>}
          </form>
          {diff && (
            <div className="card overflow-hidden">
              <div className="grid grid-cols-2 border-b border-[var(--line)] bg-[#f7f8fa] text-xs font-semibold text-[var(--muted)]">
                <div className="border-r border-[var(--line)] px-4 py-2.5">구 · {fmtDate(diff.from.effective_from)} 시행</div>
                <div className="px-4 py-2.5">신 · {fmtDate(diff.to.effective_from)} 시행</div>
              </div>
              {diff.changes.length === 0 && <p className="p-6 text-sm">달라진 조항이 없습니다.</p>}
              {diff.changes.map((c) => (
                <div key={c.provision_id} className="grid grid-cols-2 border-b border-[var(--line)] font-serif text-[15px] leading-[1.8] last:border-b-0">
                  {[c.from, c.to].map((s, i) => (
                    <div key={i} className={`px-4 py-3 ${i === 0 ? "border-r border-[var(--line)]" : ""} ${!s ? "bg-[repeating-linear-gradient(135deg,#fafbfc_0_8px,#f3f5f8_8px_16px)]" : i === 1 ? "bg-[#eef7f0]" : ""}`}>
                      {i === 1 && <span className="chip chip-green mb-1 font-sans">{CHANGE_LABEL[c.kind]}</span>}
                      {s ? <><div className="font-semibold">{s.label}{s.heading ? `(${s.heading})` : ""}</div><p>{s.text}</p></>
                        : <p className="font-sans text-[13px] text-[var(--muted)]">〈{i === 0 ? "신설" : "삭제"}〉</p>}
                    </div>
                  ))}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </main>
  );
}
