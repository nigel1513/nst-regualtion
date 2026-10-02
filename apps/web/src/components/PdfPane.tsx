"use client";

import { useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/TextLayer.css";

pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";

export function PdfPane({ fileUrl, page, bbox, label }: {
  fileUrl: string; page: number; bbox: [number, number, number, number] | null; label: string;
}) {
  const [cur, setCur] = useState(page);
  const [pages, setPages] = useState(0);
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  const width = 640;
  const scale = size ? width / size.w : 1;
  return (
    <section className="flex flex-col overflow-hidden rounded-xl bg-[#2a2f36]">
      <div className="flex items-center gap-2 bg-[#20242a] px-3 py-2.5 text-[13px] text-[#e3e7ec]">
        <span className="truncate">{label}</span>
        <div className="ml-auto flex items-center gap-1.5">
          <button className="btn h-9 w-9 justify-center border-[#444b54] bg-[#343a42] px-0 text-white" aria-label="이전 쪽" disabled={cur <= 1} onClick={() => setCur((c) => c - 1)}>‹</button>
          <span className="min-w-16 text-center">{cur} / {pages || "?"}</span>
          <button className="btn h-9 w-9 justify-center border-[#444b54] bg-[#343a42] px-0 text-white" aria-label="다음 쪽" disabled={pages > 0 && cur >= pages} onClick={() => setCur((c) => c + 1)}>›</button>
          <a className="btn border-[#e3e7ec] bg-[#e3e7ec] text-[var(--ink)]" href={fileUrl} target="_blank" rel="noreferrer">PDF 열기</a>
        </div>
      </div>
      <div className="flex justify-center overflow-auto p-6">
        <Document file={fileUrl} onLoadSuccess={(d) => setPages(d.numPages)} loading={<p className="text-sm text-[#c9ced6]">문서를 불러오는 중…</p>}
          error={<p className="text-sm text-[#c9ced6]">문서를 불러오지 못했습니다.</p>}>
          <div className="relative shadow-[0_2px_10px_rgba(0,0,0,0.35)]">
            <Page pageNumber={cur} width={width} renderAnnotationLayer={false}
              onLoadSuccess={(p) => setSize({ w: p.originalWidth, h: p.originalHeight })} />
            {bbox && cur === page && size && (
              <div aria-hidden="true" className="pointer-events-none absolute rounded-[3px] bg-[#fff1a8]/50 ring-2 ring-[#e2b400]"
                style={{ left: bbox[0] * scale - 4, top: bbox[1] * scale - 3, width: (bbox[2] - bbox[0]) * scale + 8, height: (bbox[3] - bbox[1]) * scale + 6 }} />
            )}
          </div>
        </Document>
      </div>
    </section>
  );
}
