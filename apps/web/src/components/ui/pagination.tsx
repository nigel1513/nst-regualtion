import { ChevronLeft, ChevronRight } from "lucide-react";
import Link from "next/link";
import { buttonClass } from "./button";
import { cn } from "./cn";
import { iconStroke } from "./styles";

/** "1–50 / 595"와 이전·다음. 주소(?page=)로 움직인다. */
export function Pagination({ page, size, total, href, className }: {
  page: number; size: number; total: number; href: (page: number) => string; className?: string;
}) {
  const last = Math.max(1, Math.ceil(total / size));
  const from = total === 0 ? 0 : (page - 1) * size + 1;
  const to = Math.min(total, page * size);
  const fmt = (n: number) => n.toLocaleString("ko-KR");
  const nav = (p: number, label: string, icon: React.ReactNode, disabled: boolean) =>
    disabled ? (
      <span aria-disabled="true" className={buttonClass("ghost", "sm", "pointer-events-none opacity-50")}>{icon}{label}</span>
    ) : (
      <Link href={href(p)} className={buttonClass("ghost", "sm")}>{icon}{label}</Link>
    );
  return (
    <nav aria-label="페이지" className={cn("flex items-center justify-between gap-3 text-small text-fg-muted", className)}>
      <span className="num">{fmt(from)}–{fmt(to)} / {fmt(total)}</span>
      <span className="flex items-center gap-1">
        {nav(page - 1, "이전", <ChevronLeft aria-hidden="true" strokeWidth={iconStroke} />, page <= 1)}
        <span className="num px-1">{page} / {last}</span>
        {nav(page + 1, "다음", <ChevronRight aria-hidden="true" strokeWidth={iconStroke} />, page >= last)}
      </span>
    </nav>
  );
}
