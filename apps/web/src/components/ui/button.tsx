import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";
import { cn } from "./cn";
import { focusRing } from "./styles";

/** Button (§4): primary = 잉크색 면, secondary = 흰 면+경계, ghost. 누르는 순간 scale(.97). hover 색은 즉시 바뀐다. */
const button = cva(
  [
    "press relative inline-flex shrink-0 cursor-pointer select-none items-center justify-center gap-1.5 whitespace-nowrap rounded-sm font-medium",
    "no-underline hover:no-underline disabled:cursor-not-allowed disabled:opacity-50 aria-disabled:pointer-events-none aria-disabled:opacity-50",
    "[&_svg]:size-4 [&_svg]:shrink-0",
    focusRing,
  ].join(" "),
  {
    variants: {
      variant: {
        primary: "bg-primary text-primary-fg hover:bg-primary-hover hover:text-primary-fg",
        secondary: "border border-border bg-bg-panel text-fg hover:bg-bg-hover hover:text-fg data-[popup-open]:bg-bg-hover",
        ghost: "text-fg-muted hover:bg-bg-hover hover:text-fg data-[popup-open]:bg-bg-hover data-[popup-open]:text-fg",
      },
      size: { sm: "h-7 px-2.5 text-small", md: "h-8 px-3 text-small", lg: "h-10 px-4 text-body", icon: "size-8 px-0", "icon-sm": "size-7 px-0" },
    },
    defaultVariants: { variant: "secondary", size: "md" },
  },
);

export type ButtonVariant = NonNullable<VariantProps<typeof button>["variant"]>;
export type ButtonSize = NonNullable<VariantProps<typeof button>["size"]>;

/** 버튼처럼 보이는 링크에 쓴다. */
export function buttonClass(variant?: ButtonVariant, size?: ButtonSize, className?: string): string {
  return cn(button({ variant, size }), className);
}

export type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; size?: ButtonSize };

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant, size, type = "button", ...props },
  ref,
) {
  return <button ref={ref} type={type} className={buttonClass(variant, size, className)} {...props} />;
});
