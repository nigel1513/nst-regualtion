import type { Metadata } from "next";
import { LoginForm } from "@/components/auth/LoginForm";
import { FAMILY_SITES } from "@/components/shell/SiteFooter";
import { apiGet, type Institution } from "@/lib/api";

export const metadata: Metadata = { title: "로그인 · 출연연 규정" };

/** 목업 로그인 (2026-10-04). 실제 인증은 기관 SSO와 붙일 때 바꾼다. */
export default async function LoginPage({ searchParams }: { searchParams: Promise<{ next?: string }> }) {
  const { next } = await searchParams;
  const insts = ((await apiGet<Institution[]>("/api/v1/institutions").catch(() => null)) ?? [])
    .filter((i) => i.works > 0).map((i) => ({ code: i.code, name: i.name, works: i.works }));
  return (
    <div className="flex min-h-dvh items-start justify-center bg-bg px-4 pt-[12vh] pb-12">
      <div className="w-full max-w-[420px]">
        <div className="mb-8 flex items-center gap-2">
          <span aria-hidden="true" className="flex size-7 items-center justify-center rounded-sm bg-primary text-small font-semibold text-primary-fg">N</span>
          <span className="text-heading font-semibold text-fg">출연연 규정</span>
        </div>
        <h1 className="text-display text-fg">로그인</h1>
        <p className="mb-6 mt-2 text-small text-fg-muted">시험용 로그인입니다. 고른 사람의 기관이 &lsquo;우리 기관&rsquo;이 되어 화면이 그 기관 기준으로 열립니다.</p>
        <div className="rounded-md border border-border bg-bg-panel p-5">
          <LoginForm insts={insts} next={next ?? "/"} />
        </div>
        <p className="mt-4 text-caption text-fg-subtle">실제 서비스에서는 기관 계정(SSO)으로 바뀝니다.</p>
        <nav aria-label="패밀리 사이트" className="mt-8 flex flex-wrap gap-x-4 gap-y-1 text-caption">
          {FAMILY_SITES.map((s) => (
            <a key={s.href} href={s.href} target="_blank" rel="noopener noreferrer" className="text-fg-muted no-underline hover:text-fg">{s.label}</a>
          ))}
        </nav>
      </div>
    </div>
  );
}
