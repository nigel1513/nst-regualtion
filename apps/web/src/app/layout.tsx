import type { Metadata, Viewport } from "next";
import { cookies } from "next/headers";
import { Providers } from "@/components/shell/Providers";
import { apiGet, type Institution } from "@/lib/api";
import { INST_COOKIE, resolveInst } from "@/lib/institution";
import "./globals.css";

export const metadata: Metadata = { title: "출연연 규정", description: "국가과학기술연구회·출연연 내부규정과 관련 법령" };

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#fcfcfd" },
    { media: "(prefers-color-scheme: dark)", color: "#111113" },
  ],
};

export default async function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const insts = ((await apiGet<Institution[]>("/api/v1/institutions").catch(() => null)) ?? []).map((i) => ({ code: i.code, name: i.name, works: i.works }));
  const initial = resolveInst(undefined, (await cookies()).get(INST_COOKIE)?.value, insts);
  return (
    <html lang="ko" suppressHydrationWarning>
      <body className="min-h-dvh antialiased">
        <Providers insts={insts} initialInst={initial}>{children}</Providers>
      </body>
    </html>
  );
}
