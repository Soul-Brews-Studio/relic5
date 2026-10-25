// The hub's shell, after the old ARRA Oracle Studio: a sticky top header on desktop, a bottom tab bar on a phone, and a Cmd/Ctrl-K palette to jump or search from anywhere.
import { useEffect, useRef, useState, type ComponentType, type ReactNode } from "react";
import { cx } from "./ui";
import { Alert, Pulse, Asked, Close, Gear, Globe, Psi, Tree, Columns, Menu, Rows, Disk, Home, Jobs, Live, Mark, More, Moon, Note, Plug, Search, Session, Sun } from "./Icons";

export type View = "home" | "search" | "map" | "oracles" | "family" | "live" | "memory" | "jobs" | "queries" | "compare" | "store" | "connect" | "incidents" | "settings" | "perf";
export type Theme = "dark" | "paper";
export type Layout = "top" | "side";

export const VIEWS: { id: View; label: string; icon: ComponentType<{ size?: number }>; phone?: boolean; group: 0 | 1 }[] = [
  { id: "home", label: "Home", icon: Home, phone: true, group: 0 },
  { id: "search", label: "Search", icon: Search, phone: true, group: 0 },
  { id: "map", label: "Map", icon: Globe, group: 0 },
  { id: "live", label: "Live", icon: Live, phone: true, group: 0 },
  { id: "memory", label: "Knowledge", icon: Note, phone: true, group: 0 },
  { id: "oracles", label: "Oracles", icon: Psi, group: 0 },
  { id: "family", label: "Family", icon: Tree, group: 1 },
  { id: "jobs", label: "Jobs", icon: Jobs, group: 1 },
  { id: "store", label: "Disk", icon: Disk, group: 1 },
  { id: "queries", label: "Asked", icon: Asked, group: 1 },
  { id: "compare", label: "Quality", icon: Columns, group: 1 },
  { id: "connect", label: "Connect", icon: Plug, group: 1 },
  { id: "perf", label: "Performance", icon: Pulse, group: 1 },
  { id: "incidents", label: "Incidents", icon: Alert, group: 1 },
  { id: "settings", label: "Settings", icon: Gear, group: 1 },
];

export type HubState = "ok" | "warning" | "failed" | "unknown";
const dot: Record<HubState, string> = { ok: "bg-ok", warning: "bg-warning", failed: "bg-danger", unknown: "bg-muted" };
const word: Record<HubState, string> = { ok: "Hub ready", warning: "Needs a look", failed: "Failing", unknown: "Reading" };

/** Desktop, the other layout: relic-scan's left sidebar (icons only from 1100px down), in relic5's blue. Nat,
 *  2026-10-24: "top menu cool but sidebar too is good", so the hub offers both and remembers the pick. */
export function Sidebar({ view, go, state, foot, theme, setTheme, badges, onPalette, onLayout }: {
  view: View; go: (v: View) => void; state: HubState; foot: ReactNode; theme: Theme; setTheme: (t: Theme) => void;
  badges?: Partial<Record<View, number>>; onPalette: () => void; onLayout: () => void;
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
        {!!badges?.[v.id] && <span className="ml-auto rounded-full bg-accent px-1.5 text-xs font-bold text-on-accent max-[1100px]:hidden">{badges[v.id]}</span>}
      </a>
    );
  };
  return (
    <aside className="fixed inset-y-0 left-0 z-20 hidden w-[232px] flex-col border-r border-line bg-rail px-3 pt-5 pb-4 sm:flex max-[1100px]:w-[68px] max-[1100px]:px-2.5">
      <a href="#" onClick={e => { e.preventDefault(); go("home"); }} className="mb-7 flex items-center gap-3 rounded-xl px-1.5 max-[1100px]:justify-center max-[1100px]:px-0">
        <Mark size={40} />
        <span className="max-[1100px]:hidden">
          <b className="block text-lg leading-tight font-bold text-accent">relic5</b>
          <i className="block font-mono text-xs not-italic tracking-[0.28em] text-muted">hub</i>
        </span>
      </a>
      <button type="button" onClick={onPalette} title="Search or jump (⌘K)"
        className="mb-4 flex min-h-10 items-center gap-2.5 rounded-lg border border-line bg-deep px-3 text-xs text-muted hover:border-line-strong hover:text-text max-[1100px]:justify-center max-[1100px]:px-0">
        <Search size={15} /><span className="max-[1100px]:hidden">Search or jump</span>
        <kbd className="ml-auto rounded border border-line px-1 font-mono text-xs max-[1100px]:hidden">⌘K</kbd>
      </button>
      <nav aria-label="Views" className="flex flex-col gap-0.5">
        {VIEWS.filter(v => v.group === 0).map(item)}
        <div className="mx-2.5 my-3 h-px bg-line" />
        {VIEWS.filter(v => v.group === 1).map(item)}
      </nav>
      <div className="mt-auto flex flex-col gap-3 px-2 max-[1100px]:items-center max-[1100px]:px-0">
        <div className="flex gap-2 max-[1100px]:flex-col">
        <button type="button" onClick={onLayout} aria-label="Menu across the top" title="Menu across the top"
          className="grid size-11 place-items-center rounded-lg border border-line text-muted hover:border-line-strong hover:text-text"><Rows size={18} /></button>
        <button type="button" onClick={() => setTheme(theme === "dark" ? "paper" : "dark")} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"}`}
          className="grid size-11 place-items-center rounded-lg border border-line text-muted hover:border-line-strong hover:text-text">
          {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
        </button>
        </div>
        <div className="text-xs leading-relaxed text-muted max-[1100px]:hidden">
          <b className="flex items-center gap-2 text-xs font-bold tracking-[0.14em] text-text uppercase"><span className={cx("size-2 rounded-full", dot[state])} />{word[state]}</b>
          {foot}
        </div>
        <span title={word[state]} className={cx("hidden size-2.5 rounded-full max-[1100px]:block", dot[state])} />
      </div>
    </aside>
  );
}

/** The left drawer (Nat, 2026-10-24: "add left drawer an optional"): with the top menu, the ☰ button slides the
 *  sidebar's list in over the page, on a phone too; Escape, the backdrop or picking a view closes it. */
export function NavDrawer({ open, onClose, view, go, state, foot, badges, onPalette }: {
  open: boolean; onClose: () => void; view: View; go: (v: View) => void; state: HubState; foot: ReactNode;
  badges?: Partial<Record<View, number>>; onPalette: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  // Nat, 2026-10-25: "when active left drawer it should main and can see and working with the right side". On a wide
  // screen the drawer is a panel beside the page (non-modal: the page pushes right and stays usable, a view change
  // keeps it open); on a phone it stays a modal sheet over the page.
  const wide = () => matchMedia("(min-width: 1024px)").matches;
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) { if (wide()) d.show(); else d.showModal(); }
    if (!open && d.open) d.close();
  }, [open]);
  const item = (v: (typeof VIEWS)[number]) => {
    const I = v.icon, on = view === v.id;
    return (
      <a key={v.id} href={v.id === "home" ? "#" : `#tab=${v.id}`} aria-current={on ? "page" : undefined}
        onClick={e => { e.preventDefault(); go(v.id); if (!wide()) onClose(); }}
        className={cx("flex min-h-11 items-center gap-3 rounded-lg px-3 text-sm font-medium", on ? "bg-raised text-text" : "text-soft hover:bg-raised hover:text-text")}>
        <span className={on ? "text-accent" : "text-muted"}><I size={20} /></span>{v.label}
        {!!badges?.[v.id] && <span className="ml-auto rounded-full bg-accent px-1.5 text-xs font-bold text-on-accent">{badges[v.id]}</span>}
      </a>
    );
  };
  return (
    <dialog ref={ref} onClose={onClose} onClick={e => e.target === ref.current && onClose()} aria-label="Menu"
      className="fixed inset-y-0 left-0 z-30 m-0 h-dvh max-h-none w-[280px] max-w-[85vw] border-0 border-r border-line bg-rail p-0 text-text shadow-[var(--shadow-pop)] backdrop:bg-black/50 lg:shadow-none">
      <div className="flex h-full flex-col px-3 pt-4 pb-4">
        <div className="mb-5 flex items-center gap-3 px-1.5">
          <Mark size={34} /><b className="text-lg font-bold text-accent">relic5</b>
          <button type="button" onClick={onClose} aria-label="Close the menu" className="ml-auto grid size-11 place-items-center rounded-lg text-muted hover:bg-raised hover:text-text"><Close size={18} /></button>
        </div>
        <button type="button" onClick={() => { onClose(); onPalette(); }}
          className="mb-4 flex min-h-10 items-center gap-2.5 rounded-lg border border-line bg-deep px-3 text-xs text-muted hover:border-line-strong hover:text-text">
          <Search size={15} />Search or jump<kbd className="ml-auto rounded border border-line px-1 font-mono text-xs">⌘K</kbd>
        </button>
        <nav aria-label="Views" className="flex flex-col gap-0.5">
          {VIEWS.filter(v => v.group === 0).map(item)}
          <div className="mx-3 my-3 h-px bg-line" />
          {VIEWS.filter(v => v.group === 1).map(item)}
        </nav>
        <div className="mt-auto px-3 text-xs leading-relaxed text-muted">
          <b className="flex items-center gap-2 text-xs font-bold tracking-[0.14em] text-text uppercase"><span className={cx("size-2 rounded-full", dot[state])} />{word[state]}</b>
          {foot}
        </div>
      </div>
    </dialog>
  );
}

/** Everything past the six main views (Family, Jobs, Disk, Asked, Quality, Connect) in one "More" menu, so the
 *  top bar holds six items (Nat, 2026-10-24: "too long menu"; relic4-scan's review: 5-7 visible). Escape or a click
 *  outside closes it. */
function HubMenu({ view, go, badges }: { view: View; go: (v: View) => void; badges?: Partial<Record<View, number>> }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const items = VIEWS.filter(v => v.group === 1);
  const here = items.find(v => v.id === view);
  const busy = items.reduce((n, v) => n + (badges?.[v.id] ?? 0), 0);
  useEffect(() => {
    if (!open) return;
    const off = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    addEventListener("mousedown", off); addEventListener("keydown", esc);
    return () => { removeEventListener("mousedown", off); removeEventListener("keydown", esc); };
  }, [open]);
  return (
    <div ref={ref} className="relative flex-none">
      <button type="button" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}
        className={cx("flex min-h-10 items-center gap-1.5 rounded-lg px-3 text-sm whitespace-nowrap transition-colors", here ? "bg-raised font-semibold text-text" : "text-soft hover:bg-raised hover:text-text")}>
        {here ? here.label : "More"}
        {busy > 0 && <span className="rounded-full bg-accent px-1.5 text-xs font-bold text-on-accent">{busy}</span>}
        <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden className={cx("transition-transform", open && "rotate-180")}><path d="M3 4.5l3 3 3-3" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </button>
      {open && (
        <div role="menu" className="absolute top-full left-0 z-30 mt-1.5 w-56 rounded-xl border border-line-strong bg-panel p-1.5 shadow-[var(--shadow-pop)]">
          {items.map(v => {
            const I = v.icon, on = view === v.id;
            return (
              <a key={v.id} role="menuitem" href={`#tab=${v.id}`} onClick={e => { e.preventDefault(); go(v.id); setOpen(false); }}
                className={cx("flex min-h-10 items-center gap-3 rounded-lg px-3 text-sm", on ? "bg-raised font-semibold text-text" : "text-soft hover:bg-raised hover:text-text")}>
                <span className={on ? "text-accent" : "text-muted"}><I size={18} /></span>{v.label}
                {!!badges?.[v.id] && <span className="ml-auto rounded-full bg-accent px-1.5 text-xs font-bold text-on-accent">{badges[v.id]}</span>}
              </a>
            );
          })}
        </div>
      )}
    </div>
  );
}

/** Desktop: the old ARRA Oracle Studio's header (ui-oracle apps/studio Header.tsx, 2026-04-19), not relic-scan's
 *  sidebar (Nat, 2026-10-24: "make this ui diff from relic scanner"): one sticky bar, the name in the accent, the views
 *  as text links in two groups split by a hairline, the palette, the theme and the hub's state on the right. */
export function TopNav({ view, go, state, foot, theme, setTheme, badges, onPalette, onLayout, onDrawer, version }: {
  view: View; go: (v: View) => void; state: HubState; foot: ReactNode; theme: Theme; setTheme: (t: Theme) => void;
  badges?: Partial<Record<View, number>>; onPalette: () => void; onLayout: () => void; onDrawer: () => void; version?: string;
}) {
  const link = (v: (typeof VIEWS)[number]) => {
    const on = view === v.id;
    return (
      <a key={v.id} href={v.id === "home" ? "#" : `#tab=${v.id}`} aria-current={on ? "page" : undefined}
        onClick={e => { e.preventDefault(); go(v.id); }}
        className={cx("flex min-h-10 flex-none items-center gap-2 rounded-lg px-3 text-sm whitespace-nowrap transition-colors duration-[120ms] focus-visible:outline-offset-[-2px]",
          on ? "bg-raised font-semibold text-text" : "text-soft hover:bg-[color-mix(in_srgb,var(--raised)_60%,transparent)] hover:text-text")}>
        {v.label}
        {!!badges?.[v.id] && <span className="rounded-full bg-accent px-1.5 text-xs font-bold text-on-accent">{badges[v.id]}</span>}
      </a>
    );
  };
  return (
    <header className="sticky top-0 z-20 hidden h-16 items-center gap-6 border-b border-line bg-[color-mix(in_srgb,var(--panel)_92%,transparent)] px-6 backdrop-blur sm:flex">
      <button type="button" onClick={onDrawer} aria-label="Open the menu" aria-haspopup="dialog"
        className="-mr-3 grid size-10 flex-none place-items-center rounded-lg text-muted hover:bg-raised hover:text-text"><Menu size={20} /></button>
      <a href="#" onClick={e => { e.preventDefault(); go("home"); }} className="flex flex-none items-center gap-2.5 rounded-lg">
        <Mark size={30} />
        <b className="text-xl font-bold tracking-[-0.01em] text-accent">relic5</b>
        {version && <span className="rounded bg-raised px-1.5 py-0.5 font-mono text-xs text-muted max-[1400px]:hidden">{version}</span>}
      </a>
      <nav aria-label="Views" className="flex min-w-0 flex-1 items-center gap-1">
        {VIEWS.filter(v => v.group === 0).map(link)}
        <HubMenu view={view} go={go} badges={badges} />
      </nav>
      <div className="flex flex-none items-center gap-2">
        <button type="button" onClick={onPalette}
          className="flex min-h-10 items-center gap-2.5 rounded-lg border border-line bg-deep px-3 text-xs text-muted hover:border-line-strong hover:text-text">
          <Search size={15} /><span className="max-[1500px]:hidden">Search or jump</span>
          <kbd className="rounded border border-line px-1 font-mono text-xs">⌘K</kbd>
        </button>
        <button type="button" onClick={onLayout} aria-label="Menu on the left" title="Menu on the left"
          className="grid size-10 place-items-center rounded-lg text-muted hover:bg-raised hover:text-text"><Columns size={18} /></button>
        <button type="button" onClick={() => setTheme(theme === "dark" ? "paper" : "dark")} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"}`}
          className="grid size-10 place-items-center rounded-lg text-muted hover:bg-raised hover:text-text">
          {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
        </button>
        <span className="flex items-center gap-2 pl-1 text-xs font-semibold text-soft" title={typeof foot === "string" ? foot : undefined}>
          <span className={cx("size-2 rounded-full", dot[state])} /><span className="max-[1500px]:hidden">{word[state]}</span>
        </span>
      </div>
    </header>
  );
}

/** Phone: the five views people use there, as a bottom bar; the rest are one tap away in the palette. */
export function TabBar({ view, go, onMore }: { view: View; go: (v: View) => void; onMore: () => void }) {
  return (
    <nav aria-label="Views" className="fixed inset-x-0 bottom-0 z-20 grid grid-cols-5 border-t border-line bg-[color-mix(in_srgb,var(--rail)_94%,transparent)] pb-[env(safe-area-inset-bottom)] backdrop-blur sm:hidden">
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
