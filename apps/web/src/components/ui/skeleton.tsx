import { cn } from "./cn";

/** 정적 slate-3 면, 실제 내용과 같은 크기. 반짝임 없음 (§4). */
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden="true" className={cn("rounded-sm bg-bg-hover", className)} />;
}
