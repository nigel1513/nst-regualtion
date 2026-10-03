import { Bell, ClipboardCheck, Columns3, House, List, MessageSquare, Scale, type LucideIcon } from "lucide-react";

export type NavItem = { href: string; label: string; icon: LucideIcon; match: (path: string) => boolean; soon?: boolean };

/** 사이드바·브레드크럼·⌘K가 함께 쓰는 화면 목록 (서비스 UI 개편 §1). */
export const NAV: NavItem[] = [
  { href: "/", label: "홈", icon: House, match: (p) => p === "/" },
  { href: "/regulations", label: "규정 찾기", icon: List, match: (p) => p.startsWith("/regulations") || p.startsWith("/source") },
  { href: "/compare", label: "기관 비교", icon: Columns3, match: (p) => p.startsWith("/compare") },
  { href: "/assistant", label: "규정 도우미", icon: MessageSquare, match: (p) => p.startsWith("/assistant") },
  { href: "/laws", label: "법령", icon: Scale, match: (p) => p.startsWith("/laws") },
  { href: "/review", label: "검수", icon: ClipboardCheck, match: (p) => p.startsWith("/review") },
];

export const ALERTS: NavItem = { href: "/alerts", label: "개정 알림", icon: Bell, match: (p) => p.startsWith("/alerts"), soon: true };

export function sectionFor(path: string): NavItem | undefined {
  return [...NAV, ALERTS].find((n) => n.match(path));
}
