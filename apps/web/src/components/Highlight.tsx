/** OpenSearch 하이라이트(<mark>…</mark>)를 React 요소로 그린다. 태그 밖 글자는 모두 텍스트로 이스케이프된다. */
export function Highlight({ text }: { text: string }) {
  const parts = text.split(/(<mark>[\s\S]*?<\/mark>)/g);
  return (
    <>
      {parts.map((p, i) =>
        p.startsWith("<mark>") && p.endsWith("</mark>")
          ? <mark key={i} className="bg-[var(--mark)] text-inherit">{p.slice(6, -7)}</mark>
          : <span key={i}>{p}</span>,
      )}
    </>
  );
}
