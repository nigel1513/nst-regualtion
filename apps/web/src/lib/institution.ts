/** "우리 기관" (서비스 UI 개편 §1): localStorage(try/catch) + 서버 화면이 읽는 쿠키 + 주소 ?inst=. "all" = 전체(고르지 않음). */
export const INST_STORAGE_KEY = "nst-reg-inst";
export const INST_COOKIE = "nst-inst";
export const ALL = "all";

export type InstOption = { code: string; name: string; works: number };

/** 주소 → 쿠키 순. "all"이나 없는 코드는 null(전체). */
export function resolveInst(param: string | string[] | undefined, cookie: string | undefined, known: InstOption[]): string | null {
  const raw = typeof param === "string" ? param : cookie;
  if (!raw || raw === ALL) return null;
  return known.some((i) => i.code === raw) ? raw : null;
}
