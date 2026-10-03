import { cookies } from "next/headers";
import { apiGet, type Institution } from "@/lib/api";
import { INST_COOKIE, resolveInst } from "@/lib/institution";

/** 서버 화면의 우리 기관: 주소 ?inst= → 쿠키. 기관 목록도 함께 돌려준다. */
export async function ourInstitution(param: string | string[] | undefined): Promise<{ inst: string | null; insts: Institution[] }> {
  const insts = (await apiGet<Institution[]>("/api/v1/institutions").catch(() => null)) ?? [];
  const cookie = (await cookies()).get(INST_COOKIE)?.value;
  return { inst: resolveInst(param, cookie, insts), insts };
}
