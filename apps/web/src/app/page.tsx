import { ArrowRight, MessageSquare } from "lucide-react";
import Link from "next/link";
import { ChooseInstitution } from "@/components/home/ChooseInstitution";
import { RecentViewed } from "@/components/home/RecentViewed";
import { Crumbs } from "@/components/shell/Breadcrumbs";
import { Badge } from "@/components/ui/badge";
import { buttonClass } from "@/components/ui/button";
import { InstitutionMark } from "@/components/ui/institution-mark";
import { iconStroke } from "@/components/ui/styles";
import { Table, TBody, Td, Th, THead, Tr } from "@/components/ui/table";
import { apiGet, apiTry, type Divergence, type HomeData, type InstStats, type RecentChange, workHref } from "@/lib/api";
import { fmtDate, fmtDateTime, fmtNum } from "@/lib/format";
import { ourInstitution } from "@/lib/server-inst";

/** 홈 (서비스 UI 개편 §2): 우리 기관 — 머리 수치, 다른 기관과 다른 점, 최근 바뀐 우리 규정 | 주제별 규정, 최근 본 조문. */
export default async function HomePage({ searchParams }: { searchParams: Promise<{ inst?: string }> }) {
  const sp = await searchParams;
  const { inst } = await ourInstitution(sp.inst);
  const [home, divergences] = await Promise.all([
    apiGet<HomeData>("/api/v1/home", { inst: inst ?? undefined }),
    inst ? apiTry<Divergence[]>("/api/v1/compare/divergences", { inst, limit: "5" }) : Promise.resolve(null),
  ]);
  if (!home) return null;
  return home.institution ? <InstitutionHome h={home} stats={home.institution} divergences={divergences} /> : <AllHome h={home} />;
}

function SectionHead({ id, title, link }: { id: string; title: string; link?: { href: string; label: string } }) {
  return (
    <div className="mb-3 flex items-baseline justify-between gap-3">
      <h2 id={id} className="text-heading text-fg">{title}</h2>
      {link ? <Link href={link.href} className="text-small">{link.label}</Link> : null}
    </div>
  );
}

function Header({ caption, title, meta, actions }: { caption: string; title: string; meta: React.ReactNode; actions: React.ReactNode }) {
  return (
    <div className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <div className="mb-1.5 text-caption text-fg-muted">{caption}</div>
        <h1 className="text-display break-keep text-fg">{title}</h1>
        <div className="mt-1.5 flex flex-wrap gap-x-1.5 text-small text-fg-muted">{meta}</div>
      </div>
      <div className="flex shrink-0 flex-wrap gap-2">{actions}</div>
    </div>
  );
}

const assistantButton = (
  <Link href="/assistant" className={buttonClass("primary")}>
    <MessageSquare aria-hidden="true" strokeWidth={iconStroke} />규정 도우미
  </Link>
);

function InstitutionHome({ h, stats, divergences }: { h: HomeData; stats: InstStats; divergences: Divergence[] | null }) {
  const topics = h.topics ?? [];
  return (
    <div className="max-w-[1200px]">
      <Crumbs items={[{ label: stats.name }]} />
      <Header
        caption="우리 기관"
        title={stats.name}
        meta={<>
          <span>현행 규정 <span className="num text-fg">{fmtNum(stats.current_works)}</span></span><span aria-hidden="true">·</span>
          <span>판본 <span className="num text-fg">{fmtNum(stats.versions)}</span></span><span aria-hidden="true">·</span>
          <span>마지막 수집 <span className="num">{fmtDateTime(stats.last_fetched)}</span></span>
        </>}
        actions={<>
          <Link href={`/regulations?inst=${stats.code}`} className={buttonClass("secondary")}>우리 규정 전체</Link>
          {assistantButton}
        </>}
      />
      <div className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="flex min-w-0 flex-col gap-10">
          <section aria-labelledby="diff-h">
            <div className="mb-1 flex items-baseline justify-between gap-3">
              <h2 id="diff-h" className="text-heading text-fg">다른 기관과 다른 점</h2>
              <Link href="/compare" className="text-small">전체 비교</Link>
            </div>
            <p className="mb-3 text-small text-fg-muted">같은 주제의 규정에서 우리 기관 기준이 다수 기관과 다른 항목</p>
            {divergences && divergences.length > 0 ? <DivergenceTable rows={divergences} /> : (
              <p className="rounded-md border border-dashed border-border px-4 py-5 text-small text-fg-muted">
                기관별 비교 항목을 만드는 중입니다. 준비되면 여기에 다른 점이 나옵니다.
              </p>
            )}
          </section>
          <section aria-labelledby="recent-h">
            <SectionHead id="recent-h" title="최근 바뀐 우리 규정" link={{ href: `/regulations?inst=${stats.code}&sort=recent`, label: "모두 보기" }} />
            {h.recent.length === 0 ? <p className="text-small text-fg-muted">수집한 규정이 없습니다.</p> : (
              <ul className="border-t border-border-subtle">{h.recent.map((r) => <RecentRow key={r.version_id} r={r} />)}</ul>
            )}
          </section>
        </div>
        <aside className="flex flex-col gap-8">
          {topics.length > 0 ? (
            <section aria-labelledby="topic-h">
              <h2 id="topic-h" className="mb-2 text-caption text-fg-muted">주제별 우리 규정</h2>
              <ul>
                {topics.map((t) => (
                  <li key={t.topic} className="border-b border-border-subtle last:border-0">
                    <Link href={`/compare?topic=${encodeURIComponent(t.topic)}`} className="flex justify-between py-2 text-small text-fg hover:text-fg">
                      <span>{t.label}</span><span className="num text-fg-muted">{fmtNum(t.count)}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
          <section aria-labelledby="seen-h">
            <h2 id="seen-h" className="mb-2 text-caption text-fg-muted">최근 본 조문</h2>
            <RecentViewed />
          </section>
        </aside>
      </div>
    </div>
  );
}

function DivergenceTable({ rows }: { rows: Divergence[] }) {
  return (
    <Table caption="다른 기관과 다른 점">
      <THead><Tr><Th>주제</Th><Th>항목</Th><Th>우리 기관</Th><Th>다수 기관</Th><Th><span className="sr-only">비교</span></Th></Tr></THead>
      <TBody>
        {rows.map((d) => (
          <Tr key={`${d.topic}/${d.item}`}>
            <Td><Badge>{d.topic_label}</Badge></Td>
            <Td className="font-medium">{d.item_label}</Td>
            <Td>
              <div className="num">{d.ours.value}</div>
              <Link href={workHref(d.ours.work_id, `?a=${encodeURIComponent(d.ours.path.split(".")[0])}#${d.ours.path}`)} className="text-caption font-normal">{d.ours.label}</Link>
            </Td>
            <Td>
              <div className="num">{d.majority.value}</div>
              <div className="num text-caption font-normal text-fg-muted">{fmtNum(d.majority.count)}개 기관 / {fmtNum(d.total)}</div>
            </Td>
            <Td className="text-right">
              <Link href={`/compare?${new URLSearchParams({ topic: d.topic, item: d.item })}`} className={buttonClass("secondary", "sm")}>
                비교<ArrowRight aria-hidden="true" strokeWidth={iconStroke} />
              </Link>
            </Td>
          </Tr>
        ))}
      </TBody>
    </Table>
  );
}

const KIND: Record<string, string> = { ADDED: "신설", DELETED: "삭제", MODIFIED: "개정", RENUMBERED: "조 이동" };

function RecentRow({ r }: { r: RecentChange }) {
  const c = r.changes;
  const n = c.articles.length + c.more;
  const summary = c.articles.length === 0 ? (r.kind_label === "제정" ? "새로 만든 규정" : "처음 수집한 판본이라 이전과 비교할 수 없습니다")
    : r.kind_label === "전부개정" && n > 5 ? `규정 전체를 다시 정함 · 바뀐 조 ${n.toLocaleString("ko-KR")}개` : null;
  return (
    <li className="flex gap-3 border-b border-border-subtle py-2.5">
      <span className="num w-[84px] shrink-0 pt-0.5 text-caption text-fg-muted">{fmtDate(r.effective_from)}</span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <Link href={r.href} className="font-semibold text-fg hover:text-fg">{r.title}</Link>
          <Badge tone={r.kind_label === "개정" ? "neutral" : "accent"}>{r.kind_label}</Badge>
        </div>
        {summary ? <p className="text-small text-fg-muted">{summary}</p> : (
          <p className="text-small text-fg-muted">
            {c.articles.map((a, i) => (
              <span key={a.path}>
                {i > 0 ? " · " : ""}
                <Link href={workHref(r.work_id, `?a=${encodeURIComponent(a.path)}#${a.path}`)} className="text-fg-muted hover:text-fg">{a.label}</Link>
                {a.detail ? <> {a.heading ? `${a.heading} ` : ""}<span className="num text-fg">{a.detail}</span></> : ` ${KIND[a.kind]}`}
              </span>
            ))}
            {c.more > 0 ? ` 외 ${c.more}건` : ""}
          </p>
        )}
      </div>
    </li>
  );
}

function AllHome({ h }: { h: HomeData }) {
  const rows = [...(h.institutions ?? [])].sort((a, b) => Number(b.current_works > 0) - Number(a.current_works > 0));
  const t = h.totals;
  return (
    <div className="max-w-[1200px]">
      <Header
        caption="전체 기관"
        title="기관별 규정 현황"
        meta={t ? <>
          <span>수집 기관 <span className="num text-fg">{fmtNum(t.institutions)}</span></span><span aria-hidden="true">·</span>
          <span>현행 규정 <span className="num text-fg">{fmtNum(t.current_works)}</span></span><span aria-hidden="true">·</span>
          <span>판본 <span className="num text-fg">{fmtNum(t.versions)}</span></span><span aria-hidden="true">·</span>
          <span>마지막 수집 <span className="num">{fmtDateTime(t.last_fetched)}</span></span>
        </> : null}
        actions={<><ChooseInstitution />{assistantButton}</>}
      />
      <div className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_300px]">
        <section aria-labelledby="inst-h" className="min-w-0">
          <SectionHead id="inst-h" title="기관별 현황" />
          <Table caption="기관별 현황">
            <THead>
              <Tr>
                <Th>기관</Th><Th className="text-right">현행 규정</Th><Th className="text-right">판본</Th>
                <Th>최근 개정일</Th><Th className="text-right">열린 검수</Th>
              </Tr>
            </THead>
            <TBody>
              {rows.map((r) => (
                <Tr key={r.code}>
                  <Td>
                    <Link href={`/?inst=${r.code}`} className="inline-flex items-center gap-2 whitespace-nowrap text-fg hover:text-fg">
                      <InstitutionMark code={r.code} /><span className={r.current_works ? "" : "text-fg-muted"}>{r.name}</span>
                    </Link>
                  </Td>
                  {r.current_works ? (
                    <>
                      <Td className="num text-right">{fmtNum(r.current_works)}</Td>
                      <Td className="num text-right">{fmtNum(r.versions)}</Td>
                      <Td className="num whitespace-nowrap">{fmtDate(r.last_amended)}</Td>
                      <Td className="num text-right">{r.open_reviews ? <Link href="/review">{fmtNum(r.open_reviews)}</Link> : <span className="text-fg-muted">0</span>}</Td>
                    </>
                  ) : (
                    <Td colSpan={4} className="text-fg-muted">수집 전</Td>
                  )}
                </Tr>
              ))}
            </TBody>
          </Table>
        </section>
        <aside>
          <h2 className="mb-2 text-caption text-fg-muted">최근 본 조문</h2>
          <RecentViewed />
        </aside>
      </div>
    </div>
  );
}
