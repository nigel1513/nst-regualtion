import { cn } from "./cn";

/** 기관 표시: 기관 코드(KASI, KICT …)를 인디고 3단계 면 + 11단계 글자로. 두 글자로 줄이면 KIST·KICT·KIER가 겹쳐 코드 전체를 쓴다. */
export function InstitutionMark({ code, className }: { code: string | null | undefined; full?: boolean; className?: string }) {
  if (!code) return null;
  return (
    <span aria-hidden="true"
      className={cn("inline-flex h-5 min-w-[22px] shrink-0 items-center justify-center rounded-sm bg-accent-soft px-1 font-mono text-micro font-semibold tracking-tight text-accent-fg", className)}>
      {code}
    </span>
  );
}
