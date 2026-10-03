import { Crumbs } from "@/components/shell/Breadcrumbs";
import { RegulationTable } from "@/components/regulations/RegulationTable";
import { apiGet, type RegulationsResult } from "@/lib/api";
import { fmtNum } from "@/lib/format";

/** 법령: law.go.kr에서 받아 둔 법령·행정규칙 (규정이 인용하는 것만). */
export default async function LawsPage() {
  const data = await apiGet<RegulationsResult>("/api/v1/regulations?kind=law&status=all&sort=title&size=500");
  return (
    <div className="max-w-[1200px]">
      <Crumbs items={[]} />
      <h1 className="text-display text-fg">법령</h1>
      <p className="mb-6 mt-1.5 text-small text-fg-muted">규정이 인용하는 법령·행정규칙 <span className="num">{fmtNum(data?.total ?? 0)}</span>건 · law.go.kr 원문 기준</p>
      {data?.items.length ? <RegulationTable rows={data.items} topics={false} /> : <p className="text-small text-fg-muted">받아 둔 법령이 없습니다.</p>}
    </div>
  );
}
