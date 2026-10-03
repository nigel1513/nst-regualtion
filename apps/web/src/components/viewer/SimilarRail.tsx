"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { InstitutionMark } from "@/components/ui/institution-mark";
import { Skeleton } from "@/components/ui/skeleton";
import type { CompareData, ProvisionCompare, SimilarResult } from "@/lib/api";

type Values = { item: string; ours: string | null; by: Record<string, { value: string | null; same: boolean | null }> };

/** 이 조로 뽑은 비교값이 있으면, 비슷한 조를 가진 기관들의 같은 항목 값과 같음/다름을 가져온다. 없으면 null. */
async function compareValues(pvId: number, insts: string[]): Promise<Values | null> {
  const loc = await fetch(`/api/v1/provision/compare?pv=${pvId}`).then((r) => (r.ok ? (r.json() as Promise<ProvisionCompare>) : null)).catch(() => null);
  const cell = loc?.cells[0];
  const codes = insts.filter((c) => /^[A-Za-z0-9]+$/.test(c));
  if (!loc?.institution || !cell || codes.length === 0) return null;
  const q = new URLSearchParams({ topic: cell.topic, inst: codes.join(","), ours: loc.institution });
  const d = await fetch(`/api/v1/compare?${q}`).then((r) => (r.ok ? (r.json() as Promise<CompareData>) : null)).catch(() => null);
  const row = d?.cells[cell.item];
  if (!row) return null;
  const by: Values["by"] = {};
  for (const code of codes) {
    const c = row[code];
    if (c?.status === "value") by[code] = { value: c.value, same: c.differs == null ? null : !c.differs };
  }
  return { item: cell.item_label, ours: cell.value, by };
}

/**
 * 오른쪽 레일 "다른 기관의 같은 조항" (§3): 고른 조와 의미가 비슷한 다른 기관 조 상위 5개 (GET /api/v1/provision/similar).
 * 같음/다름 배지는 기관 비교 값(compare_cell)이 생기면 붙인다.
 */
export function SimilarRail({ pvId, label }: { pvId: number; label: string }) {
  const [data, setData] = useState<SimilarResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [values, setValues] = useState<Values | null>(null);
  useEffect(() => {
    if (!data?.items.length) return;
    let alive = true;
    compareValues(pvId, data.items.map((x) => x.institution)).then((v) => alive && setValues(v));
    return () => { alive = false; };
  }, [data, pvId]);
  useEffect(() => {
    let alive = true;
    fetch(`/api/v1/provision/similar?pv=${pvId}&limit=5`)
      .then(async (r) => {
        if (!r.ok) throw new Error(r.status === 503 ? "검색 색인에 연결할 수 없습니다." : "불러오지 못했습니다.");
        return (await r.json()) as SimilarResult;
      })
      .then((d) => alive && setData(d))
      .catch((e: Error) => alive && setError(e.message));
    return () => { alive = false; };
  }, [pvId]);
  return (
    <section aria-labelledby="similar-h" aria-busy={!data && !error}>
      <div className="flex items-baseline justify-between gap-2">
        <h2 id="similar-h" className="text-caption text-fg-muted">다른 기관의 같은 조항</h2>
        <Link href={`/compare?${new URLSearchParams({ view: "side", pv: String(pvId) })}`} className="text-small">나란히 보기</Link>
      </div>
      <p className="mt-0.5 text-caption font-normal text-fg-muted">{label}과 내용이 비슷한 조항{values ? ` · ${values.item} 우리 ${values.ours}` : ""}</p>
      {error ? <p className="mt-3 text-small text-fg-muted">{error}</p> : null}
      {!data && !error ? (
        <div className="mt-2 flex flex-col">
          {[0, 1, 2].map((i) => (
            <div key={i} className="border-b border-border-subtle py-3">
              <Skeleton className="h-4 w-40" /><Skeleton className="mt-2 h-4 w-28" /><Skeleton className="mt-2 h-10 w-full" />
            </div>
          ))}
        </div>
      ) : null}
      {data && data.items.length === 0 ? <p className="mt-3 text-small text-fg-muted">비슷한 조항을 찾지 못했습니다.</p> : null}
      {data && data.items.length > 0 ? (
        <ul className="mt-1">
          {data.items.map((s) => (
            <li key={`${s.work_id}#${s.article_path}`} className="border-b border-border-subtle py-3 last:border-0">
              <div className="mb-1 flex items-center gap-1.5">
                <InstitutionMark code={s.institution} />
                <span className="truncate text-small font-semibold text-fg">{s.institution_name}</span>
              </div>
              <Link href={s.href} className="text-small">{s.title} {s.label}{s.heading ? ` (${s.heading})` : ""}</Link>
              {values?.by[s.institution] ? (
                <p className="mt-1 flex items-center gap-1.5 text-small text-fg">
                  <span className="num">{values.by[s.institution].value}</span>
                  {values.by[s.institution].same != null ? <Badge tone={values.by[s.institution].same ? "success" : "warning"}>{values.by[s.institution].same ? "같음" : "다름"}</Badge> : null}
                </p>
              ) : null}
              <p className="mt-1 line-clamp-3 text-small text-fg-muted">{s.snippet}</p>
            </li>
          ))}
        </ul>
      ) : null}
      {data && data.items.length > 0 ? <p className="mt-2 text-caption font-normal text-fg-muted">의미 검색으로 찾았습니다. 값이 같은지는 원문으로 확인하세요.</p> : null}
    </section>
  );
}
