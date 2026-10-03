"use client";
import { Dialog as BaseDialog } from "@base-ui/react/dialog";
import { Command } from "cmdk";
import { FileText, Hash, MessageSquare, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { cn } from "@/components/ui/cn";
import { iconStroke } from "@/components/ui/styles";
import { workHref } from "@/lib/api";
import { NAV } from "@/lib/nav";

type Suggest = { title: string; work_id: string; institution: string | null; institution_name: string | null };
type Lookup = { doc_id: string; work_id: string; path: string; article_path: string; full_label: string; institution_name: string | null; heading: string | null };

const Ctx = createContext<{ open: boolean; setOpen: (o: boolean) => void }>({ open: false, setOpen: () => {} });
export const useCommandPalette = () => useContext(Ctx);

/** 서버 검색: 150ms 기다렸다가 규정명 자동완성과 조문 번호 조회를 함께 부른다. 늦게 온 옛 응답은 버린다. */
function useRemote(q: string) {
  const [state, setState] = useState<{ q: string; regs: Suggest[]; arts: Lookup[] }>({ q: "", regs: [], arts: [] });
  useEffect(() => {
    const t = q.trim();
    if (!t) return;
    const ctl = new AbortController();
    const timer = window.setTimeout(async () => {
      const get = async <T,>(url: string): Promise<T | null> => {
        try {
          const r = await fetch(url, { signal: ctl.signal });
          return r.ok ? ((await r.json()) as T) : null;
        } catch {
          return null;
        }
      };
      const [regs, look] = await Promise.all([
        get<Suggest[]>(`/api/v1/search/suggest?${new URLSearchParams({ q: t, size: "6" })}`),
        t.length >= 2 && /\d|조/.test(t) ? get<{ hits: Lookup[] }>(`/api/v1/search/lookup?${new URLSearchParams({ q: t, size: "5" })}`) : null,
      ]);
      if (!ctl.signal.aborted) setState({ q: t, regs: regs ?? [], arts: look?.hits ?? [] });
    }, 150);
    return () => { ctl.abort(); window.clearTimeout(timer); };
  }, [q]);
  return state.q === q.trim() ? state : { q: "", regs: [], arts: [] };
}

const itemClass = cn(
  "flex h-9 cursor-pointer select-none items-center gap-2.5 rounded-sm px-2 text-body text-fg outline-none",
  "data-[selected=true]:bg-bg-hover [&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:text-fg-muted",
);
const groupClass = "[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:pt-2 [&_[cmdk-group-heading]]:text-caption [&_[cmdk-group-heading]]:text-fg-muted";

/**
 * ⌘K 명령 팔레트 (§1): 규정·조문 찾기, 화면 이동, 입력한 말을 규정 도우미로 넘기기. 열고 닫을 때 애니메이션 없음.
 */
export function CommandPaletteProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const router = useRouter();
  const remote = useRemote(q);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const go = useCallback((href: string) => {
    setOpen(false);
    setQ("");
    router.push(href);
  }, [router]);

  const t = q.trim();
  const navs = useMemo(() => NAV.filter((n) => !t || n.label.includes(t)), [t]);
  // 결과가 새로 오면 맨 위 항목을 고른다 (cmdk는 처음 그린 항목을 계속 붙잡는다). 사용자가 옮긴 선택은 같은 결과 안에서만 유지
  const first = remote.arts[0] ? `art-${remote.arts[0].doc_id}` : remote.regs[0] ? `reg-${remote.regs[0].work_id}` : t.length >= 2 ? "ask" : navs[0] ? `nav-${navs[0].href}` : "";
  const [picked, setPicked] = useState<{ key: string; value: string }>({ key: "", value: "" });
  const resultKey = `${remote.q}|${remote.arts.length}|${remote.regs.length}|${t.length >= 2}`;
  const selected = picked.key === resultKey ? picked.value : first;
  return (
    <Ctx.Provider value={{ open, setOpen }}>
      {children}
      <BaseDialog.Root open={open} onOpenChange={(o) => { setOpen(o); if (!o) setQ(""); }}>
        <BaseDialog.Portal>
          <BaseDialog.Backdrop className="fixed inset-0 z-[var(--z-dialog)] bg-scrim" />
          <BaseDialog.Popup aria-label="찾기와 이동"
            className="fixed inset-x-0 top-[12dvh] z-[var(--z-dialog)] mx-auto w-[calc(100vw-2rem)] max-w-[640px] overflow-hidden rounded-lg border border-border bg-bg-panel shadow-dialog outline-none">
            <Command label="찾기와 이동" shouldFilter={false} loop value={selected} onValueChange={(v) => setPicked({ key: resultKey, value: v })}
              className="flex w-full flex-col text-fg">
              <div className="flex items-center gap-2 border-b border-border px-3">
                <Search aria-hidden="true" className="size-4 shrink-0 text-fg-muted" strokeWidth={iconStroke} />
                <Command.Input value={q} onValueChange={setQ} placeholder="규정 이름, 조문(예: 천문연 여비규정 27조) 또는 질문"
                  className="h-11 w-full min-w-0 bg-transparent text-body text-fg outline-none placeholder:text-fg-subtle" />
              </div>
              <Command.List className="max-h-[min(400px,60dvh)] scroll-py-1 overflow-y-auto p-1">
                {remote.arts.length > 0 ? (
                  <Command.Group heading="조문" className={groupClass}>
                    {remote.arts.map((a) => (
                      <Command.Item key={a.doc_id} value={`art-${a.doc_id}`} className={itemClass}
                        onSelect={() => go(workHref(a.work_id, `?${new URLSearchParams({ a: a.article_path })}#${a.path}`))}>
                        <Hash aria-hidden="true" strokeWidth={iconStroke} />
                        <span className="min-w-0 flex-1 truncate">{a.full_label}{a.heading ? ` (${a.heading})` : ""}</span>
                        <span className="max-w-[40%] shrink-0 truncate text-small text-fg-muted">{a.institution_name ?? "법령"}</span>
                      </Command.Item>
                    ))}
                  </Command.Group>
                ) : null}
                {remote.regs.length > 0 ? (
                  <Command.Group heading="규정" className={groupClass}>
                    {remote.regs.map((r) => (
                      <Command.Item key={r.work_id} value={`reg-${r.work_id}`} className={itemClass} onSelect={() => go(workHref(r.work_id))}>
                        <FileText aria-hidden="true" strokeWidth={iconStroke} />
                        <span className="min-w-0 flex-1 truncate">{r.title}</span>
                        <span className="max-w-[40%] shrink-0 truncate text-small text-fg-muted">{r.institution_name ?? "법령"}</span>
                      </Command.Item>
                    ))}
                  </Command.Group>
                ) : null}
                {t.length >= 2 ? (
                  <Command.Group heading="규정 도우미" className={groupClass}>
                    <Command.Item value="ask" className={itemClass} onSelect={() => go(`/assistant?${new URLSearchParams({ q: t })}`)}>
                      <MessageSquare aria-hidden="true" strokeWidth={iconStroke} />
                      <span className="min-w-0 flex-1 truncate">도우미에게 묻기: “{t}”</span>
                    </Command.Item>
                  </Command.Group>
                ) : null}
                {navs.length > 0 ? (
                  <Command.Group heading="이동" className={groupClass}>
                    {navs.map((n) => {
                      const Icon = n.icon;
                      return (
                        <Command.Item key={n.href} value={`nav-${n.href}`} className={itemClass} onSelect={() => go(n.href)}>
                          <Icon aria-hidden="true" strokeWidth={iconStroke} />
                          <span className="min-w-0 flex-1 truncate">{n.label}</span>
                        </Command.Item>
                      );
                    })}
                  </Command.Group>
                ) : null}
                <Command.Empty className="px-3 py-6 text-center text-small text-fg-muted">찾는 규정이 없습니다</Command.Empty>
              </Command.List>
            </Command>
          </BaseDialog.Popup>
        </BaseDialog.Portal>
      </BaseDialog.Root>
    </Ctx.Provider>
  );
}
