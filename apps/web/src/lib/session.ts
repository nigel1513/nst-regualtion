/**
 * 목업 로그인 (2026-10-04): 실제 인증은 나중에 기관 SSO와 붙인다. 지금은 계정을 고르면 그 사람의 기관이
 * "우리 기관"이 되어 홈·규정 찾기·기관 비교가 미리 걸러진다. 권한 차이는 없다.
 * 쿠키 하나(nst-session, base64url JSON)만 쓴다 — 서버 화면과 proxy가 읽는다.
 */
export const SESSION_COOKIE = "nst-session";
export const REVIEWER_KEY = "nst-reg-reviewer"; // 검수 처리 기록(by)에 쓰는 이름 (ReviewTable)

export type Role = "행정원" | "연구자" | "관리자";
export type SessionUser = { id: string; name: string; role: Role; inst: string | null; dept: string };

/** 목업 계정. inst=null은 전체 기관을 보는 연구회 관리자. */
export const MOCK_USERS: SessionUser[] = [
  { id: "kasi-admin", name: "김지원", role: "행정원", inst: "KASI", dept: "총무팀" },
  { id: "etri-research", name: "이서연", role: "연구자", inst: "ETRI", dept: "AI연구본부" },
  { id: "kist-admin", name: "박민준", role: "행정원", inst: "KIST", dept: "재무회계팀" },
  { id: "kriss-research", name: "최유진", role: "연구자", inst: "KRISS", dept: "양자기술연구소" },
  { id: "nst-manager", name: "정하늘", role: "관리자", inst: null, dept: "국가과학기술연구회 정책기획부" },
];

const b64 = (s: string) => btoa(String.fromCharCode(...new TextEncoder().encode(s))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const unb64 = (s: string) => new TextDecoder().decode(Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/")), (c) => c.charCodeAt(0)));

export function encodeSession(u: SessionUser): string {
  return b64(JSON.stringify(u));
}

export function decodeSession(raw: string | undefined | null): SessionUser | null {
  if (!raw) return null;
  try {
    const u = JSON.parse(unb64(decodeURIComponent(raw)));
    if (typeof u?.name !== "string" || !u.name.trim()) return null;
    return { id: String(u.id ?? "custom"), name: u.name.trim().slice(0, 40), role: (["행정원", "연구자", "관리자"].includes(u.role) ? u.role : "행정원") as Role,
      inst: typeof u.inst === "string" && u.inst ? u.inst : null, dept: typeof u.dept === "string" ? u.dept.slice(0, 60) : "" };
  } catch {
    return null;
  }
}
