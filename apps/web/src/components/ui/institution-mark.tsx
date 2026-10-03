import { cn } from "./cn";

/** 기관 표시: 기관 코드 앞 두 글자(작은 칸) 또는 코드 전체. 인디고 3단계 면 + 11단계 글자, 반경 sm. */
export function InstitutionMark({ code, full, className }: { code: string | null | undefined; full?: boolean; className?: string }) {
  if (!code) return null;
  return (
    <span
      aria-hidden="true"
      className={cn(
        "inline-flex h-[22px] shrink-0 items-center justify-center rounded-sm bg-accent-soft text-micro font-semibold text-accent-fg",
        full ? "px-1.5" : "w-[22px]",
        className,
      )}
    >
      {full ? code : code.slice(0, 2)}
    </span>
  );
}
