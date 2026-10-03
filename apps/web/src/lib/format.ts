export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "-";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return `${y}. ${m}. ${d}.`;
}

export const STATE_LABEL: Record<string, string> = {
  CURRENT: "현행", HISTORICAL: "연혁", FUTURE: "시행 예정", UNDATED: "시행일 미상",
};
export const STATUS_LABEL: Record<string, string> = {
  CONFIRMED: "시행일 확인", UNCERTAIN: "시행일 추정", CONFLICT: "시행일 충돌",
};
export const BASIS_LABEL: Record<string, string> = {
  api: "법령 API", supplement: "부칙", history: "개정 이력", alio: "ALIO 개정일", filename: "파일명", none: "근거 없음",
};
export const REL_LABEL: Record<string, string> = {
  BASIS: "근거", DELEGATION: "위임", IMPLEMENTS: "시행", MUTATIS: "준용", EXCEPTION: "예외", CITATION: "참조",
};
export const CHANGE_LABEL: Record<string, string> = {
  ADDED: "신설", DELETED: "삭제", MODIFIED: "개정", RENUMBERED: "조 이동", ANNOTATION_ONLY: "주석만 변경",
};
export const TASK_LABEL: Record<string, string> = {
  PARSE: "구조 파싱", EFFECTIVE_DATE: "시행일", REFERENCE: "참조 해석", CONFLICT: "출처 충돌", LOW_TEXT: "텍스트 부족",
  REF_LAW_AMBIGUOUS: "법령명 모호", REF_LAW_GONE: "인용 조문 삭제·폐지",
};

/** "2026. 10. 2. 23:27" (한국 시간). */
export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "-";
  const p = new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", year: "numeric", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }).formatToParts(d);
  const g = (t: string) => p.find((x) => x.type === t)?.value ?? "";
  return `${g("year")}. ${g("month")}. ${g("day")}. ${g("hour")}:${g("minute")}`;
}

export function fmtNum(n: number | null | undefined): string {
  return n == null ? "-" : n.toLocaleString("ko-KR");
}

const CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳";

/** 조항 경로 → 화면 라벨: a27.p3 → 제27조 제3항, a3-2 → 제3조의2, annex1 → 별표 1, form2 → 서식 2. 기술 경로를 그대로 보이지 않는다. */
export function pathLabel(path: string): string {
  const out: string[] = [];
  for (const seg of path.split("#")[0].split(".")) {
    let m: RegExpMatchArray | null;
    if ((m = seg.match(/^a(\d+)(?:-(\d+))?/))) out.push(`제${m[1]}조${m[2] ? `의${m[2]}` : ""}`);
    else if ((m = seg.match(/^p(\d+)/))) out.push(CIRCLED[Number(m[1]) - 1] ?? `제${m[1]}항`);
    else if ((m = seg.match(/^i(\d+)(?:-(\d+))?/))) out.push(`제${m[1]}호${m[2] ? `의${m[2]}` : ""}`);
    else if ((m = seg.match(/^s(.)/))) out.push(`${m[1]}목`);
    else if ((m = seg.match(/^annex(\d+)(?:-(\d+))?/))) out.push(`별표 ${m[1]}${m[2] ? `의${m[2]}` : ""}`);
    else if ((m = seg.match(/^form(\d+)(?:-(\d+))?/))) out.push(`서식 ${m[1]}${m[2] ? `의${m[2]}` : ""}`);
    else if (seg.startsWith("supp")) out.push("부칙");
    else out.push(seg);
  }
  return out.join(" ");
}
