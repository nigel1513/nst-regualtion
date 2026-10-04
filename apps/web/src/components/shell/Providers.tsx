"use client";
import { ThemeProvider } from "next-themes";
import type { ReactNode } from "react";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { InstOption } from "@/lib/institution";
import type { SessionUser } from "@/lib/session";
import { AppShell } from "./AppShell";
import { InstitutionProvider } from "./InstitutionContext";

export function Providers({ insts, initialInst, user, children }: { insts: InstOption[]; initialInst: string | null; user: SessionUser | null; children: ReactNode }) {
  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange storageKey="nst-reg-theme">
      <TooltipProvider>
        <InstitutionProvider insts={insts} initial={initialInst} user={user}>
          <AppShell>{children}</AppShell>
        </InstitutionProvider>
      </TooltipProvider>
    </ThemeProvider>
  );
}
