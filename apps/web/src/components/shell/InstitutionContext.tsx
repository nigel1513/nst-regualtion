"use client";
import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useMemo, type ReactNode } from "react";
import { INST_COOKIE, INST_STORAGE_KEY, type InstOption } from "@/lib/institution";
import { REVIEWER_KEY, SESSION_COOKIE, type SessionUser } from "@/lib/session";

/**
 * 우리 기관 = 로그인한 사람의 기관 (목업 로그인, 2026-10-04). 고르는 화면은 없다 — 기관을 바꾸려면 다른 계정으로 로그인한다.
 * inst=null은 전체 기관(연구회 관리자). 기관은 미리 거르는 기본값일 뿐, 다른 기관 규정도 모두 볼 수 있다.
 */
type Ctx = { inst: string | null; insts: InstOption[]; current: InstOption | null; user: SessionUser | null; logout: () => void };

const InstCtx = createContext<Ctx | null>(null);

export function InstitutionProvider({ insts, initial, user, children }: {
  insts: InstOption[]; initial: string | null; user: SessionUser | null; children: ReactNode;
}) {
  const router = useRouter();
  const logout = useCallback(() => {
    for (const c of [SESSION_COOKIE, INST_COOKIE]) document.cookie = `${c}=; path=/; max-age=0; samesite=lax`;
    try {
      window.localStorage.removeItem(INST_STORAGE_KEY);
      window.localStorage.removeItem(REVIEWER_KEY);
    } catch {
      /* 저장소가 막혀 있어도 쿠키를 지웠으니 로그아웃된다 */
    }
    router.replace("/login");
    router.refresh();
  }, [router]);

  const value = useMemo<Ctx>(() => ({
    inst: initial, insts, current: insts.find((i) => i.code === initial) ?? null, user, logout,
  }), [initial, insts, user, logout]);
  return <InstCtx.Provider value={value}>{children}</InstCtx.Provider>;
}

export function useInstitution(): Ctx {
  const c = useContext(InstCtx);
  if (!c) throw new Error("InstitutionProvider 밖");
  return c;
}
