import { wordDiff } from "@/lib/diff";

/** 구 → 신 한 덩어리로: 지운 말은 빨강 취소선, 더한 말은 초록 밑줄. 색만으로 구분하지 않도록 <del>/<ins>를 쓴다. */
export function DiffText({ from, to }: { from: string; to: string }) {
  return (
    <>
      {wordDiff(from, to).map((p, i) =>
        p.kind === "same" ? <span key={i}>{p.text}</span>
          : p.kind === "del" ? <del key={i} className="rounded-xs bg-danger-soft text-danger line-through decoration-danger/60">{p.text}</del>
          : <ins key={i} className="rounded-xs bg-success-soft text-success no-underline">{p.text}</ins>,
      )}
    </>
  );
}
