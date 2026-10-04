"use client";
import { Check } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/components/ui/cn";
import { InstitutionMark } from "@/components/ui/institution-mark";
import { SelectMenu } from "@/components/ui/select";
import { field, focusRing } from "@/components/ui/styles";
import { ALL, INST_COOKIE, INST_STORAGE_KEY, type InstOption } from "@/lib/institution";
import { encodeSession, MOCK_USERS, REVIEWER_KEY, SESSION_COOKIE, type Role, type SessionUser } from "@/lib/session";

const YEAR = 60 * 60 * 24 * 365;

/** 목업 로그인: 계정을 고르거나 이름·기관을 적는다. 기관이 "우리 기관"이 된다. */
export function LoginForm({ insts, next }: { insts: InstOption[]; next: string }) {
  const router = useRouter();
  const [pick, setPick] = useState<string>(MOCK_USERS[0].id);
  const [name, setName] = useState("");
  const [inst, setInst] = useState<string | null>(null);
  const [role, setRole] = useState<Role>("행정원");
  const nameOf = (code: string | null) => (code ? insts.find((i) => i.code === code)?.name ?? code : "전체 기관");

  function signIn(u: SessionUser) {
    document.cookie = `${SESSION_COOKIE}=${encodeURIComponent(encodeSession(u))}; path=/; max-age=${YEAR}; samesite=lax`;
    document.cookie = `${INST_COOKIE}=${encodeURIComponent(u.inst ?? ALL)}; path=/; max-age=${YEAR}; samesite=lax`;
    try {
      window.localStorage.setItem(INST_STORAGE_KEY, u.inst ?? "");
      window.localStorage.setItem(REVIEWER_KEY, u.name);
    } catch {
      /* 저장소가 막혀도 쿠키로 동작한다 */
    }
    router.replace(next.startsWith("/") && !next.startsWith("//") ? next : "/");
    router.refresh();
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (pick !== "custom") return signIn(MOCK_USERS.find((u) => u.id === pick)!);
    if (!name.trim()) return;
    signIn({ id: "custom", name: name.trim(), role, inst, dept: "" });
  }

  const custom = pick === "custom";
  return (
    <form onSubmit={submit} className="flex flex-col gap-5">
      <fieldset className="flex flex-col gap-1">
        <legend className="mb-2 text-caption text-fg-muted">계정 고르기</legend>
        {MOCK_USERS.map((u) => (
          <label key={u.id} className={cn("flex h-12 cursor-pointer items-center gap-3 rounded-sm border px-3",
            pick === u.id ? "border-border-strong bg-bg-hover" : "border-transparent hover:bg-bg-hover")}>
            <input type="radio" name="account" value={u.id} checked={pick === u.id} onChange={() => setPick(u.id)} className={cn("sr-only")} />
            <span className="flex w-11 shrink-0 justify-center">
              {u.inst ? <InstitutionMark code={u.inst} /> : <span aria-hidden="true" className="flex h-[22px] items-center rounded-sm bg-bg-active px-1.5 text-micro text-fg-muted">전체</span>}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-body font-medium text-fg">{u.name} <span className="font-normal text-fg-muted">· {u.role}</span></span>
              <span className="block truncate text-small text-fg-muted">{nameOf(u.inst)} · {u.dept}</span>
            </span>
            {pick === u.id ? <Check aria-hidden="true" className="size-4 text-fg" strokeWidth={2} /> : null}
          </label>
        ))}
        <label className={cn("flex h-12 cursor-pointer items-center gap-3 rounded-sm border px-3",
          custom ? "border-border-strong bg-bg-hover" : "border-transparent hover:bg-bg-hover")}>
          <input type="radio" name="account" value="custom" checked={custom} onChange={() => setPick("custom")} className="sr-only" />
          <span className="flex w-11 shrink-0 justify-center"><span aria-hidden="true" className="flex size-[22px] items-center justify-center rounded-sm border border-dashed border-border-strong text-micro text-fg-muted">+</span></span>
          <span className="flex-1 text-body font-medium text-fg">직접 입력</span>
          {custom ? <Check aria-hidden="true" className="size-4 text-fg" strokeWidth={2} /> : null}
        </label>
      </fieldset>

      {custom ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="flex flex-col gap-1.5 sm:col-span-2">
            <span className="text-caption text-fg-muted">이름</span>
            <input value={name} onChange={(e) => setName(e.target.value)} autoFocus required maxLength={40} className={field} />
          </label>
          <div className="flex flex-col gap-1.5">
            <span id="inst-l" className="text-caption text-fg-muted">기관</span>
            <SelectMenu aria-label="기관" value={inst ?? ALL} onValueChange={(v) => setInst(!v || v === ALL ? null : v)}
              options={[{ value: ALL, label: "전체 기관 (연구회)" }, ...insts.map((i) => ({ value: i.code, label: i.name }))]} />
          </div>
          <div className="flex flex-col gap-1.5">
            <span className="text-caption text-fg-muted">역할</span>
            <SelectMenu aria-label="역할" value={role} onValueChange={(v) => setRole((v as Role) ?? "행정원")}
              options={(["행정원", "연구자", "관리자"] as Role[]).map((r) => ({ value: r, label: r }))} />
          </div>
        </div>
      ) : null}

      <Button type="submit" variant="primary" size="lg" className={cn("w-full", focusRing)} disabled={custom && !name.trim()}>로그인</Button>
    </form>
  );
}
