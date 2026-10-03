/**
 * 규정 도우미 SSE 프록시. next.config의 rewrites도 /api/*를 넘기지만, 스트림이 버퍼링되지 않도록
 * 이 경로만 직접 받아 백엔드 응답 본문(ReadableStream)을 그대로 흘려보낸다. 브라우저가 끊으면(req.signal) 백엔드 요청도 끊는다.
 */
const API = process.env.REG_API_URL ?? "http://127.0.0.1:21061";

export const dynamic = "force-dynamic";

export async function POST(req: Request): Promise<Response> {
  const search = new URL(req.url).search;
  let upstream: Response;
  try {
    upstream = await fetch(`${API}/api/v1/chat${search}`, {
      method: "POST",
      headers: { "content-type": "application/json", accept: req.headers.get("accept") ?? "text/event-stream" },
      body: await req.text(),
      signal: req.signal,
      cache: "no-store",
    });
  } catch {
    return Response.json({ detail: "규정 도우미 서버에 연결하지 못했습니다" }, { status: 502 });
  }
  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "content-type": upstream.headers.get("content-type") ?? "application/json",
      "cache-control": "no-cache, no-transform",
      "x-accel-buffering": "no",
    },
  });
}
