"use client";
import { setLocalValue, useLocalValue } from "@/lib/hooks";

/** 로그인 전까지 담당자 이름은 사용자가 적은 이름 (이 브라우저에만). "내 담당"과 처리 기록(by)에 쓴다. */
const KEY = "nst-reg-reviewer";

export function useReviewer(): [string | null, (name: string | null) => void] {
  const v = useLocalValue(KEY);
  return [v && v.trim() ? v : null, (name) => setLocalValue(KEY, (name ?? "").trim().slice(0, 50))];
}
