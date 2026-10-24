// The hub's shell, after relic-scan's app (#side in relic4-scan src/page/shell.css): a fixed left sidebar on desktop
// (icons only from 1100px down), a bottom tab bar on a phone, and a Cmd/Ctrl-K palette to jump or search from anywhere.
import { useEffect, useRef, useState, type ComponentType, type ReactNode } from "react";
import { cx } from "./ui";
import { Asked, Columns, Disk, Home, Jobs, Live, Mark, More, Moon, Note, Plug, Search, Session, Sun } from "./Icons";

export type View = "home" | "search" | "live" | "memory" | "jobs" | "queries" | "compare" | "store" | "connect";
export type Theme = "dark" | "paper";

export const VIEWS: { id: View; label: string; icon: ComponentType<{ size?: number }>; phone?: boolean; group: 0 | 1 }[] = [
  { id: "home", label: "Home", icon: Home, phone: true, group: 0 },
  { id: "search", label: "Search", icon: Search, phone: true, group: 0 },
  { id: "live", label: "Live", icon: Live, phone: true, group: 0 },
  { id: "memory", label: "Knowledge", icon: Note, phone: true, group: 0 },
  { id: "jobs", label: "Jobs", icon: Jobs, phone: true, group: 1 },
  { id: "store", label: "Disk", icon: Disk, group: 1 },
  { id: "queries", label: "Asked", icon: Asked, group: 1 },
  { id: "compare", label: "Search quality", icon: Columns, group: 1 },
  { id: "connect", label: "Connect", icon: Plug, group: 1 },
];

export type HubState = "ok" | "warning" | "failed" | "unknown";
const dot: Record<HubState, string> = { ok: "bg-ok", warning: "bg-warning", failed: "bg-danger", unknown: "bg-muted" };
const word: Record<HubState, string> = { ok: "Hub ready", warning: "Needs a look", failed: "Failing", unknown: "Reading" };

export function Sidebar({ view, go, state, foot, theme, setTheme, badges }: {
  view: View; go: (v: View) => void; state: HubState; foot: ReactNode; theme: Theme; setTheme: (t: Theme) => void;
  badges?: Partial<Record<View, number>>;
}) {
  const item = (v: (typeof VIEWS)[number]) => {
    const I = v.icon, on = view === v.id;
    return (
      <a key={v.id} href={v.id === "home" ? "#" : `#tab=${v.id}`} aria-current={on ? "page" : undefined} title={v.label}
        onClick={e => { e.preventDefault(); go(v.id); }}
        className={cx("group flex min-h-11 items-center gap-3 rounded-lg px-2.5 text-sm font-medium whitespace-nowrap transition-colors duration-[120ms] ease-[var(--ease-out)] max-[1100px]:justify-center max-[1100px]:px-0",
          on ? "bg-raised text-text" : "text-soft hover:bg-[color-mix(in_srgb,var(--raised)_60%,transparent)] hover:text-text")}>
        <span className={cx("flex-none transition-colors", on ? "text-accent" : "text-muted group-hover:text-text")}><I size={20} /></span>
        <span className="max-[1100px]:hidden">{v.label}</span>
        {!!badges?.[v.id] && <span className="ml-auto rounded-full bg-amber px-1.5 text-xs font-bold text-on-amber max-[1100px]:hidden">{badges[v.id]}</span>}
      </a>
    );
  };
  return (
    <aside className="fixed inset-y-0 left-0 z-20 hidden w-[232px] flex-col border-r border-line bg-rail px-3 pt-5 pb-4 sm:flex max-[1100px]:w-[68px] max-[1100px]:px-2.5">
      <a href="#" onClick={e => { e.preventDefault(); go("home"); }} className="mb-7 flex items-center gap-3 rounded-xl px-1.5 max-[1100px]:justify-center max-[1100px]:px-0">
        <Mark size={40} />
        <span className="max-[1100px]:hidden">
          <b className="block text-base leading-tight font-extrabold tracking-[0.12em] text-text">RELIC5</b>
          <i className="block font-mono text-xs not-italic tracking-[0.28em] text-muted">hub</i>
        </span>
      </a>
      <nav aria-label="Views" className="flex flex-col gap-0.5">
        {VIEWS.filter(v => v.group === 0).map(item)}
        <div className="mx-2.5 my-3 h-px bg-line" />
        {VIEWS.filter(v => v.group === 1).map(item)}
      </nav>
      <div className="mt-auto flex flex-col gap-3 px-2 max-[1100px]:items-center max-[1100px]:px-0">
        <button type="button" onClick={() => setTheme(theme === "dark" ? "paper" : "dark")} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"}`}
          className="grid size-11 place-items-center rounded-lg border border-line text-muted hover:border-line-strong hover:text-text">
          {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
        </button>
        <div className="text-xs leading-relaxed text-muted max-[1100px]:hidden">
          <b className="flex items-center gap-2 text-xs font-bold tracking-[0.14em] text-text uppercase"><span className={cx("size-2 rounded-full", dot[state])} />{word[state]}</b>
          {foot}
        </div>
        <span title={word[state]} className={cx("hidden size-2.5 rounded-full max-[1100px]:block", dot[state])} />
      </div>
    </aside>
  );
}

/** Phone: the five views people use there, as a bottom bar; the rest are one tap away in the palette. */
export function TabBar({ view, go, onMore }: { view: View; go: (v: View) => void; onMore: () => void }) {
  return (
    <nav aria-label="Views" className="fixed inset-x-0 bottom-0 z-20 grid grid-cols-6 border-t border-line bg-[color-mix(in_srgb,var(--rail)_94%,transparent)] pb-[env(safe-area-inset-bottom)] backdrop-blur sm:hidden">
      {VIEWS.filter(v => v.phone).map(v => {
        const I = v.icon, on = view === v.id;
        return (
          <button key={v.id} type="button" onClick={() => go(v.id)} aria-current={on ? "page" : undefined}
            className={cx("flex min-h-14 flex-col items-center justify-center gap-1 text-xs font-semibold", on ? "text-accent" : "text-muted")}>
            <I size={20} />{v.label}
          </button>
        );
      })}
      <button type="button" onClick={onMore} aria-haspopup="dialog" className="flex min-h-14 flex-col items-center justify-center gap-1 text-xs font-semibold text-muted">
        <More size={20} />More
      </button>
    </nav>
  );
}

/** Cmd/Ctrl-K: type a view's name to go there, or anything else to search it. */
export interface PaletteSession { sid: string; name: string; repo: string; ts: string }
export function Palette({ open, onClose, go, search, recent, sessions, openSession }: {
  open: boolean; onClose: () => void; go: (v: View) => void; search: (q: string) => void; recent: string[];
  sessions: PaletteSession[]; openSession: (s: PaletteSession) => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [q, setQ] = useState("");
  const [i, setI] = useState(0);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) { back.current = document.activeElement as HTMLElement | null; setQ(""); setI(0); d.showModal(); }
    if (!open && d.open) { d.close(); back.current?.focus?.(); }
  }, [open]);
  const back = useRef<HTMLElement | null>(null);
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  const found = words.length ? sessions.filter(x => words.every(w => (x.name + " " + x.repo + " " + x.sid).toLowerCase().includes(w))).slice(0, 6) : [];
  const views = VIEWS.filter(v => !q || v.label.toLowerCase().includes(q.toLowerCase()));
  const items: { key: string; label: ReactNode; run: () => void; hint: string }[] = [
    ...(q.trim() ? [{ key: "q", label: <>Search for <b className="text-text">“{q.trim()}”</b></>, run: () => search(q.trim()), hint: "↵" }] : []),
    ...found.map(x => ({ key: "s" + x.sid, label: <><Session size={14} className="mr-1.5 inline -mt-0.5 text-muted" />{x.name} <span className="text-muted">· {x.repo}</span></>, run: () => openSession(x), hint: "session" })),
    ...views.map(v => ({ key: v.id, label: <>Go to {v.label}</>, run: () => go(v.id), hint: "view" })),
    ...(!q ? recent.slice(0, 5).map(r => ({ key: "r" + r, label: <>{r}</>, run: () => search(r), hint: "asked before" })) : []),
  ];
  const pick = (n: number) => { items[n]?.run(); onClose(); };
  return (
    <dialog ref={ref} onClose={onClose} onClick={e => e.target === ref.current && onClose()} aria-label="Search or jump"
      className="mx-auto mt-[12vh] w-[min(640px,92vw)] rounded-2xl border border-line-strong bg-panel p-0 text-text shadow-[var(--shadow-pop)]">
      <label className="flex items-center gap-3 border-b border-line px-5">
        <span className="text-muted"><Search size={18} /></span>
        <input autoFocus value={q} onChange={e => { setQ(e.target.value); setI(0); }} placeholder="Search, find a session, or jump to a view…" aria-label="Search, find a session, or jump to a view"
          role="combobox" aria-expanded="true" aria-controls="pal-list" aria-activedescendant={items[i] ? `pal-${i}` : undefined} aria-autocomplete="list"
          onKeyDown={e => {
            if (e.key === "ArrowDown") { e.preventDefault(); setI(x => Math.min(x + 1, items.length - 1)); }
            if (e.key === "ArrowUp") { e.preventDefault(); setI(x => Math.max(x - 1, 0)); }
            if (e.key === "Enter") { e.preventDefault(); pick(i); }
          }}
          className="h-14 min-w-0 flex-1 bg-transparent text-base text-text placeholder:text-faint focus-visible:outline-none" />
        <kbd className="rounded-md border border-line px-1.5 font-mono text-xs text-muted">esc</kbd>
      </label>
      <ul id="pal-list" role="listbox" aria-label="Results" className="m-0 max-h-[50vh] list-none overflow-y-auto p-2">
        {items.map((it, n) => (
          <li key={it.key} id={`pal-${n}`} role="option" aria-selected={n === i} onClick={() => pick(n)} onMouseEnter={() => setI(n)}
            className={cx("flex min-h-11 cursor-pointer items-center gap-3 rounded-lg px-3 text-sm", n === i ? "bg-raised text-text" : "text-soft")}>
            <span className="min-w-0 flex-1 truncate">{it.label}</span><span className="text-xs text-muted">{it.hint}</span>
          </li>
        ))}
      </ul>
    </dialog>
  );
}
