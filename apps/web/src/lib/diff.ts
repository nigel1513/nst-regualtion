/** 낱말 단위 차이 (개정 이력 탭, eCFR식: 삭제 빨강 취소선 · 추가 초록). 조문 하나는 길어야 수백 낱말이라 LCS로 충분하다. */
export type DiffPart = { kind: "same" | "del" | "add"; text: string };

const tokenize = (s: string) => s.match(/\s+|[^\s]+/g) ?? [];

export function wordDiff(a: string, b: string): DiffPart[] {
  const x = tokenize(a), y = tokenize(b);
  if (x.length * y.length > 400_000) return [{ kind: "del", text: a }, { kind: "add", text: b }];
  const n = x.length, m = y.length;
  const dp: Uint16Array[] = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) {
    dp[i][j] = x[i] === y[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  }
  const out: DiffPart[] = [];
  const push = (kind: DiffPart["kind"], text: string) => {
    const last = out[out.length - 1];
    if (last && last.kind === kind) last.text += text; else out.push({ kind, text });
  };
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (x[i] === y[j]) { push("same", x[i]); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) push("del", x[i++]);
    else push("add", y[j++]);
  }
  while (i < n) push("del", x[i++]);
  while (j < m) push("add", y[j++]);
  return out;
}
