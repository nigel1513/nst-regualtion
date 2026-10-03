import Link from "next/link";
import { AbolishBadge } from "@/components/AbolishBadge";
import { Badge } from "@/components/ui/badge";
import { InstitutionMark } from "@/components/ui/institution-mark";
import { Table, TBody, Td, Th, THead, Tr } from "@/components/ui/table";
import type { RegulationRow } from "@/lib/api";
import { fmtDate, fmtNum } from "@/lib/format";

function Cells({ r, topics, showInst }: { r: RegulationRow; topics: boolean; showInst: boolean }) {
  return (
    <>
      <Td className="min-w-[220px]">
        <span className="inline-flex flex-wrap items-center gap-x-2 gap-y-1">
          <Link href={r.href} className="font-semibold text-fg hover:text-fg">{r.title}</Link>
          <AbolishBadge status={r.status} abolishedOn={r.abolished_on} />
        </span>
      </Td>
      {showInst ? (
        <Td className="whitespace-nowrap">
          {r.institution ? <span className="inline-flex items-center gap-1.5"><InstitutionMark code={r.institution} />{r.institution_name}</span>
            : <span className="text-fg-muted">법령</span>}
        </Td>
      ) : null}
      <Td className="whitespace-nowrap">
        {topics ? (r.topics.length ? <span className="flex flex-wrap gap-1">{r.topics.map((t) => <Badge key={t.topic}>{t.label}</Badge>)}</span> : <span className="text-fg-muted">—</span>)
          : <span className="text-fg-muted">{r.kind_label}</span>}
      </Td>
      <Td className="num whitespace-nowrap">{fmtDate(r.effective_from)}</Td>
      <Td className="num text-right">{fmtNum(r.articles)}</Td>
    </>
  );
}

function Head({ topics, showInst }: { topics: boolean; showInst: boolean }) {
  return (
    <THead>
      <Tr>
        <Th>규정</Th>{showInst ? <Th>기관</Th> : null}<Th>{topics ? "주제" : "종류"}</Th><Th>시행일</Th><Th className="text-right">조문</Th>
      </Tr>
    </THead>
  );
}

/** 목록 표 (§3): 규정, 기관, 주제(없으면 종류), 시행일, 조문 수. */
export function RegulationTable({ rows, topics }: { rows: RegulationRow[]; topics: boolean }) {
  return (
    <Table caption="찾은 규정">
      <Head topics={topics} showInst />
      <TBody>{rows.map((r) => <Tr key={r.id} className="hover:bg-bg-hover"><Cells r={r} topics={topics} showInst /></Tr>)}</TBody>
    </Table>
  );
}

/** 기관별 묶기: 한 표 안에서 기관마다 머리 행을 둔다 (카드로 나누지 않는다). */
export function GroupedTable({ rows, topics, ours }: { rows: RegulationRow[]; topics: boolean; ours: string | null }) {
  const groups = new Map<string, RegulationRow[]>();
  for (const r of rows) {
    const k = r.institution ?? "";
    groups.set(k, [...(groups.get(k) ?? []), r]);
  }
  const keys = [...groups.keys()].sort((a, b) => Number(b === ours) - Number(a === ours));
  return (
    <Table caption="기관별로 묶은 규정">
      <Head topics={topics} showInst={false} />
      {keys.map((k) => {
        const g = groups.get(k)!;
        return (
          <TBody key={k || "law"}>
            <Tr className="bg-bg-subtle">
              <Th scope="colgroup" colSpan={4} className="h-9 text-small font-semibold text-fg">
                <span className="inline-flex items-center gap-2">
                  {k ? <InstitutionMark code={k} /> : null}{g[0].institution_name ?? "법령"}
                  {k === ours ? <span className="font-normal text-fg-muted">(우리)</span> : null}
                  <span className="num font-normal text-fg-muted">{fmtNum(g.length)}</span>
                </span>
              </Th>
            </Tr>
            {g.map((r) => <Tr key={r.id} className="hover:bg-bg-hover"><Cells r={r} topics={topics} showInst={false} /></Tr>)}
          </TBody>
        );
      })}
    </Table>
  );
}
