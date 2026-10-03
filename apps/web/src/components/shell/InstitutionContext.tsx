"use client";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { ALL, INST_COOKIE, INST_STORAGE_KEY, type InstOption } from "@/lib/institution";

type Ctx = {
  inst: string | null; insts: InstOption[]; current: InstOption | null;
  choose: (code: string | null) => void; pickerOpen: boolean; setPickerOpen: (open: boolean) => void;
};

const InstCtx = createContext<Ctx | null>(null);

function persist(code: string | null) {
  try {
    window.localStorage.setItem(INST_STORAGE_KEY, code ?? "");
  } catch {
    /* 사생활 보호 모드 등: 이 탭에서만 유지 */
  }
  document.cookie = `${INST_COOKIE}=${encodeURIComponent(code ?? ALL)}; path=/; max-age=31536000; samesite=lax`;
}

/** 화면이 주소(?inst=)로 기관을 받는 곳: 고르면 그 주소로 옮긴다. 다른 곳은 새로고침만. */
const URL_SCREENS = ["/", "/regulations"];

export function InstitutionProvider({ insts, initial, children }: { insts: InstOption[]; initial: string | null; children: ReactNode }) {
  const [inst, setInst] = useState<string | null>(initial);
  const [pickerOpen, setPickerOpen] = useState(false);
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    const fromUrl = new URLSearchParams(window.location.search).get("inst");
    let stored: string | null = null;
    try {
      stored = window.localStorage.getItem(INST_STORAGE_KEY);
    } catch {
      stored = null;
    }
    if (fromUrl && (fromUrl === ALL || insts.some((i) => i.code === fromUrl))) {
      const code = fromUrl === ALL ? null : fromUrl;
      setInst(code);
      persist(code);
    } else if (stored !== null) {
      setInst(stored || null);
    } else if (!document.cookie.includes(`${INST_COOKIE}=`)) {
      setPickerOpen(true);           // 처음 방문: 기관을 고르게 한다 (건너뛰면 전체)
    }
  }, [insts]);

  const choose = useCallback((code: string | null) => {
    setInst(code);
    persist(code);
    setPickerOpen(false);
    if (URL_SCREENS.includes(pathname)) router.push(`${pathname}?inst=${code ?? ALL}`);
    else router.refresh();
  }, [pathname, router]);

  const value = useMemo<Ctx>(() => ({
    inst, insts, current: insts.find((i) => i.code === inst) ?? null, choose, pickerOpen, setPickerOpen,
  }), [inst, insts, choose, pickerOpen]);
  return <InstCtx.Provider value={value}>{children}</InstCtx.Provider>;
}

export function useInstitution(): Ctx {
  const c = useContext(InstCtx);
  if (!c) throw new Error("InstitutionProvider 밖");
  return c;
}
