"use client";
import { useSyncExternalStore } from "react";

const noop = () => () => {};

/** 서버 렌더에서는 false, 브라우저에서는 true (하이드레이션 뒤). */
export function useIsClient(): boolean {
  return useSyncExternalStore(noop, () => true, () => false);
}

const LOCAL_EVENT = "nst-local-storage";

function subscribeLocal(cb: () => void) {
  window.addEventListener("storage", cb);
  window.addEventListener(LOCAL_EVENT, cb);
  return () => { window.removeEventListener("storage", cb); window.removeEventListener(LOCAL_EVENT, cb); };
}

/** localStorage 값 하나를 구독한다 (막혀 있으면 null). 서버에서는 null. */
export function useLocalValue(key: string): string | null {
  return useSyncExternalStore(subscribeLocal, () => {
    try {
      return window.localStorage.getItem(key);
    } catch {
      return null;
    }
  }, () => null);
}

/** localStorage에 쓰고 같은 탭의 구독자에게 알린다. 실패해도 조용히. */
export function setLocalValue(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* 사생활 보호 모드 등 */
  }
  window.dispatchEvent(new Event(LOCAL_EVENT));
}
