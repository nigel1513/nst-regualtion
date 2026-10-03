"use client";
import { useEffect } from "react";
import { pushRecent } from "@/lib/recent";

/** 본 조문을 홈의 "최근 본 조문"에 남긴다. */
export function TrackRecent({ href, title, label, inst }: { href: string; title: string; label: string; inst: string | null }) {
  useEffect(() => pushRecent({ href, title, label, inst }), [href, title, label, inst]);
  return null;
}
