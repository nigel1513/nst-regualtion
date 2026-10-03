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
    <section className="flex flex-col overflow-hidden rounded-md border border-border bg-bg-active">
      <div className="flex items-center gap-2 border-b border-border bg-bg-subtle px-3 py-2.5 text-small text-fg">
        <span className="truncate">{label}</span>
        <div className="ml-auto flex items-center gap-1.5">
          <button className="btn h-9 w-9 justify-center px-0" aria-label="이전 쪽" disabled={cur <= 1} onClick={() => setCur((c) => c - 1)}>‹</button>
          <span className="min-w-16 text-center">{cur} / {pages || "?"}</span>
          <button className="btn h-9 w-9 justify-center px-0" aria-label="다음 쪽" disabled={pages > 0 && cur >= pages} onClick={() => setCur((c) => c + 1)}>›</button>
          <a className="btn btn-dark" href={fileUrl} target="_blank" rel="noreferrer">PDF 열기</a>
        </div>
      </div>
      <div className="flex justify-center overflow-auto p-6">
        <Document file={fileUrl} onLoadSuccess={(d) => setPages(d.numPages)} loading={<p className="text-body text-fg-muted">문서를 불러오는 중…</p>}
          error={<p className="text-body text-fg-muted">문서를 불러오지 못했습니다.</p>}>
          <div className="relative border border-border">
            <Page pageNumber={cur} width={width} renderAnnotationLayer={false}
              onLoadSuccess={(p) => setSize({ w: p.originalWidth, h: p.originalHeight })} />
            {bbox && cur === page && size && (
              <div aria-hidden="true" className="pointer-events-none absolute rounded-xs bg-mark/60 ring-2 ring-warning-solid"
                style={{ left: bbox[0] * scale - 4, top: bbox[1] * scale - 3, width: (bbox[2] - bbox[0]) * scale + 8, height: (bbox[3] - bbox[1]) * scale + 6 }} />
            )}
          </div>
        </Document>
      </div>
    </section>
  );
}
