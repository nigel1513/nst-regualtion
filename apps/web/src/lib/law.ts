export function lawHref(lawId: string, extra = ""): string {
  return `/laws/${encodeURIComponent(lawId)}${extra}`;
}

/** 별표번호 6자리(앞 4자리 번호 + 뒤 2자리 가지번호) → "6의2" */
export function annexNo(n: string | null): string {
  if (!n || !/^\d{6}$/.test(n)) return n ?? "";
  const main = Number(n.slice(0, 4));
  const branch = Number(n.slice(4));
  return branch ? `${main}의${branch}` : String(main);
}
