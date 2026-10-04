import { ArrowUpRight } from "lucide-react";
import { iconStroke } from "@/components/ui/styles";

/** 패밀리 사이트: 모 사이트(NAIS 홈페이지)와 NAIS가 운영하는 서비스. 내부망 주소 — 정식 도메인이 생기면 여기만 바꾼다. */
export const FAMILY_SITES = [
  { label: "국가과학AI연구센터(NAIS)", href: "http://192.168.0.3:21050/" },
  { label: "NAIS 연구데이터 포털", href: "http://192.168.0.3:21051/" },
  { label: "국가과학기술연구회", href: "https://www.nst.re.kr/" },
] as const;

export function SiteFooter() {
  return (
    <footer className="border-t border-border px-4 py-5 text-caption text-fg-muted md:px-6 xl:px-8">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <p>국가과학기술연구회 국가과학AI연구센터 · 출연연 규정·법령 서비스</p>
        <nav aria-label="패밀리 사이트" className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
          <span className="text-fg-subtle">패밀리 사이트</span>
          {FAMILY_SITES.map((s) => (
            <a key={s.href} href={s.href} target="_blank" rel="noopener noreferrer"
              className="inline-flex items-center gap-0.5 text-fg-muted no-underline hover:text-fg hover:no-underline">
              {s.label}<ArrowUpRight aria-hidden="true" className="size-3" strokeWidth={iconStroke} />
              <span className="sr-only">(새 창)</span>
            </a>
          ))}
        </nav>
      </div>
    </footer>
  );
}
