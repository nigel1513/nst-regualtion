"use client";

import dynamic from "next/dynamic";

// react-pdf는 브라우저 API(document, window)를 쓰므로 서버 렌더링에서 제외한다
export const PdfPaneLazy = dynamic(() => import("./PdfPane").then((m) => m.PdfPane), {
  ssr: false,
  loading: () => <p className="p-6 text-body text-[var(--muted)]">문서 보기를 준비하는 중…</p>,
});
