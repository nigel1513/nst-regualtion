/** 최근 본 조문 (§2 오른쪽 레일): 이 브라우저에만 남는다. 저장소가 막혀 있으면 조용히 비운다. */
export type RecentView = { href: string; title: string; label: string; inst: string | null; at: number };
import { setLocalValue } from "@/lib/hooks";

export const RECENT_KEY = "nst-reg-recent";
const MAX = 8;

export function parseRecent(raw: string | null): RecentView[] {
  try {
    const v = JSON.parse(raw ?? "[]");
    return Array.isArray(v) ? (v as RecentView[]).slice(0, MAX) : [];
  } catch {
    return [];
  }
}

function readRecent(): RecentView[] {
  try {
    return parseRecent(window.localStorage.getItem(RECENT_KEY));
  } catch {
    return [];
  }
}

export function pushRecent(item: Omit<RecentView, "at">): void {
  const rest = readRecent().filter((x) => x.href !== item.href);
  setLocalValue(RECENT_KEY, JSON.stringify([{ ...item, at: Date.now() }, ...rest].slice(0, MAX)));
}
