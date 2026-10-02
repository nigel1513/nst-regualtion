import { QaChat } from "@/components/QaChat";
import { apiGet, type Institution } from "@/lib/api";

export default async function QaPage() {
  const insts = (await apiGet<Institution[]>("/api/v1/institutions")) ?? [];
  return (
    <main className="mx-auto max-w-4xl px-6 py-6">
      <h1 className="mb-1 text-2xl font-bold">질의응답</h1>
      <p className="mb-5 text-[13px] text-[var(--muted)]">소속 기관 규정의 근거 원문을 먼저 보여드리고 그 안에서만 설명합니다. 법적 판단이 아니며 소관부서 확인이 필요합니다.</p>
      <QaChat institutions={insts.map((i) => ({ code: i.code, name: i.name }))} />
    </main>
  );
}
