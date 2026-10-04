import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE } from "@/lib/session";

/** 목업 로그인: 세션 쿠키가 없으면 로그인 화면으로 (낙관적 검사 — 실제 인증은 나중에 SSO). */
export function proxy(request: NextRequest) {
  if (request.cookies.get(SESSION_COOKIE)?.value) return NextResponse.next();
  const url = new URL("/login", request.url);
  const next = request.nextUrl.pathname + request.nextUrl.search;
  if (next !== "/") url.searchParams.set("next", next);
  return NextResponse.redirect(url);
}

export const config = {
  // 화면만 막는다: API 프록시, 정적 파일, 로그인 화면은 그대로
  matcher: ["/((?!api|_next|login|favicon.ico|.*\\.(?:png|svg|ico|woff2?|css|js|map)$).*)"],
};
