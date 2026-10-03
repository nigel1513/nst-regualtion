/** 부품이 함께 쓰는 클래스 조각. 값은 모두 globals.css 토큰이다 (NAIS 디자인 시스템 §2, §4). */

/** 키보드 포커스: 2px --focus 외곽선, 2px 떨어짐. 마우스 클릭에는 없음. */
export const focusRing = "outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

/** 입력 칸: 링이 경계 안쪽에 선다. */
export const fieldFocus = "outline-none focus-visible:border-focus focus-visible:ring-3 focus-visible:ring-focus-ring";

/** 32px 입력 칸 (Input, Select 트리거). */
export const field = [
  "h-8 w-full min-w-0 rounded-sm border border-border-strong bg-bg-panel px-2.5 text-body text-fg",
  "placeholder:text-fg-subtle",
  fieldFocus,
  "disabled:cursor-not-allowed disabled:bg-bg-subtle disabled:text-fg-subtle",
].join(" ");

/** 떠 있는 면 (팝오버·셀렉트·메뉴): 트리거에서 150ms scale(0.97)+opacity로 나타나고 100ms에 사라진다. */
export const floating = [
  "rounded-md border border-border bg-bg-panel text-fg shadow-popover outline-none",
  "origin-[var(--transform-origin)] transition-[transform,opacity] duration-[var(--dur-fast)] ease-[var(--ease-out)]",
  "data-[starting-style]:[transform:scale(0.97)] data-[starting-style]:opacity-0",
  "data-[ending-style]:opacity-0 data-[ending-style]:duration-[var(--dur-exit)]",
].join(" ");

/** 떠 있는 목록 안 32px 줄. */
export const listItem = [
  "relative flex h-8 cursor-default select-none items-center gap-2 rounded-sm px-2 text-body text-fg outline-none",
  "data-[highlighted]:bg-bg-hover data-[disabled]:pointer-events-none data-[disabled]:text-fg-subtle",
  "[&_svg]:size-4 [&_svg]:shrink-0",
].join(" ");

/** lucide 아이콘 선 굵기 1.75 (§1). */
export const iconStroke = 1.75;
