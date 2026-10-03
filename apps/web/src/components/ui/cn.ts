import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

/** tailwind-merge가 토큰 이름을 알아야 `text-body`(크기)와 `text-fg`(색)를 서로 지우지 않는다. */
const twMerge = extendTailwindMerge({
  extend: {
    theme: {
      text: ["display", "title", "heading", "body", "small", "caption", "mono", "micro", "long"],
      shadow: ["popover", "dialog", "raised"],
    },
  },
});

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
