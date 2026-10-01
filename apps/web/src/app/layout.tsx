import type { Metadata } from "next";
import { IBM_Plex_Sans_KR, Noto_Serif_KR } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const ui = IBM_Plex_Sans_KR({ weight: ["400", "500", "600", "700"], subsets: ["latin"], variable: "--font-ui", display: "swap" });
const law = Noto_Serif_KR({ weight: ["400", "600"], subsets: ["latin"], variable: "--font-law", display: "swap" });

export const metadata: Metadata = { title: "NST 규정·법령", description: "국가과학기술연구회·출연연 내부규정과 관련 법령" };

const NAV = [
  { href: "/regulations", label: "규정" },
  { href: "/search", label: "검색" },
  { href: "/review", label: "검수" },
];

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko" className={`${ui.variable} ${law.variable}`}>
      <body className="min-h-screen font-sans antialiased">
        <header className="flex h-14 items-center gap-5 bg-[var(--ink)] px-6 text-white">
          <Link href="/regulations" className="flex items-center gap-2.5 whitespace-nowrap text-[15px] font-semibold text-white hover:no-underline">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
              <path d="M4 4h11l5 5v11H4z" /><path d="M15 4v5h5M8 13h8M8 17h5" />
            </svg>
            NST 규정·법령
          </Link>
          <nav className="flex gap-1" aria-label="주 메뉴">
            {NAV.map((n) => (
              <Link key={n.href} href={n.href} className="rounded-md px-3 py-2 text-sm text-[#c9ced6] hover:bg-[#262b32] hover:text-white hover:no-underline">
                {n.label}
              </Link>
            ))}
          </nav>
        </header>
        {children}
      </body>
    </html>
  );
}
