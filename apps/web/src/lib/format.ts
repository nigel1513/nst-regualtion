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
};
