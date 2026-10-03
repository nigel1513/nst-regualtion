import { Check } from "lucide-react";
import * as React from "react";
import { cn } from "./cn";
import { field } from "./styles";

/** 32px 입력 칸 (§4 Input). */
export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...props }, ref) {
  return <input ref={ref} className={cn(field, className)} {...props} />;
});

/**
 * 네이티브 체크박스를 16px 상자로 그린다. 실제 input이 24px 영역을 덮어 키보드·폼 동작을 그대로 쓴다. 선택 = --primary 면.
 */
export const Checkbox = React.forwardRef<HTMLInputElement, Omit<React.InputHTMLAttributes<HTMLInputElement>, "type">>(function Checkbox(
  { className, ...props },
  ref,
) {
  return (
    <span className={cn("relative inline-flex size-4 shrink-0 align-middle", className)}>
      <input ref={ref} type="checkbox" className="peer absolute -inset-1 z-10 m-0 cursor-pointer appearance-none opacity-0 disabled:cursor-not-allowed" {...props} />
      <span
        aria-hidden="true"
        className={cn(
          "pointer-events-none flex size-4 items-center justify-center rounded-xs border border-border-strong bg-bg-panel text-primary-fg",
          "peer-checked:border-primary peer-checked:bg-primary peer-disabled:opacity-50",
          "peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-focus",
          "[&>svg]:invisible peer-checked:[&>svg]:visible",
        )}
      >
        <Check className="size-3" strokeWidth={3} />
      </span>
    </span>
  );
});
