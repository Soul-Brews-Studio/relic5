import { useEffect, useState } from "react";
import { usePoll } from "./api";
import type { Status } from "./types";
import { Rail } from "./components/Rail";
import { StatusBar } from "./components/StatusBar";
import { cx, Kbd, Seg, State } from "./components/ui";
import { SearchView, type SearchState } from "./views/SearchView";
import { LiveView } from "./views/LiveView";
import { JobsView } from "./views/JobsView";
import { QueriesView } from "./views/QueriesView";
import { CompareView } from "./views/CompareView";
import { StoreView } from "./views/StoreView";
import { GlancePage } from "./views/GlancePage";

const TABS = ["search", "live", "jobs", "queries", "compare", "store"] as const;
type Tab = (typeof TABS)[number];
type Theme = "dark" | "paper";

/** The URL hash holds the view: #tab=search&q=...&horizon=...&with=...&repo=...&machine=..., so a view is a link and
 *  back/forward work (relic4-scan src/page/shell.js ?view= deep links). */
/** No hash (the hub's root) = the glance page; #tab=... = the hub's tabs. */
const isGlance = () => !location.hash || location.hash === "#" || location.hash.startsWith("#/glance");

function readHash() {
  const h = new URLSearchParams(location.hash.slice(1));
  const tab = (TABS as readonly string[]).includes(h.get("tab") ?? "") ? (h.get("tab") as Tab) : "search";
  return { tab, machine: h.get("machine") ?? "", search: { q: h.get("q") ?? "", horizon: h.get("horizon") ?? "", with: h.get("with") ?? "", repo: h.get("repo") ?? "" } };
}
function writeHash(tab: Tab, machine: string, s: SearchState) {
  const h = new URLSearchParams({ tab });
  if (machine) h.set("machine", machine);
  for (const [k, v] of Object.entries(s)) if (v) h.set(k, v);
  const next = "#" + h;
  if (next !== location.hash) history.pushState(null, "", next);
}

export function App() {
  const [view, setView] = useState(readHash);
  const [theme, setTheme] = useState<Theme>(() => (localStorage.getItem("relic5-theme") as Theme) || "dark");
  const [focusKey, setFocusKey] = useState(0);
  const status = usePoll<Status>("/api/status", 15000);
  const s = status.data;

  useEffect(() => { document.documentElement.dataset.theme = theme; localStorage.setItem("relic5-theme", theme); }, [theme]);
  const [glance, setGlance] = useState(isGlance);
  useEffect(() => { if (!glance) writeHash(view.tab, view.machine, view.search); }, [view, glance]);
  useEffect(() => {
    const pop = () => { setGlance(isGlance()); setView(readHash()); };
    window.addEventListener("hashchange", pop);
    const key = (e: KeyboardEvent) => {
      if (e.key === "/" && (e.target as HTMLElement).tagName !== "INPUT") { e.preventDefault(); setView(v => ({ ...v, tab: "search" })); setFocusKey(k => k + 1); }
    };
    window.addEventListener("popstate", pop); window.addEventListener("keydown", key);
    return () => { window.removeEventListener("popstate", pop); window.removeEventListener("hashchange", pop); window.removeEventListener("keydown", key); };
  }, []);

  if (glance) return <GlancePage s={s} error={status.error} at={status.at} theme={theme} setTheme={setTheme} />;
  const dot = status.error ? "bg-danger" : s ? "bg-accent shadow-[0_0_0_4px_var(--accent-wash)]" : "bg-warning";
  return (
    <div className="grid h-dvh grid-rows-[auto_minmax(0,1fr)] overflow-hidden">
      <header className="z-10 flex min-h-[58px] flex-wrap items-center gap-3.5 border-b border-line bg-panel px-4 py-2">
        <a href="#" title="the glance page" className="flex items-baseline whitespace-nowrap font-sans text-[15px] font-bold text-accent">
          RELIC<span className="font-medium text-faint">5</span><small className="ml-2.5 font-mono text-[10px] text-faint">{s ? `${s.code.name} ${s.code.version}` : "hub"}</small>
        </a>
        <Seg label="Theme" value={theme} onChange={setTheme} options={[{ value: "dark", label: "Dark" }, { value: "paper", label: "Paper" }]} />
        <span className="hidden gap-1 text-[10px] text-faint lg:flex"><Kbd>/</Kbd> search <Kbd>j</Kbd><Kbd>k</Kbd> move <Kbd>↵</Kbd> open <Kbd>esc</Kbd> close</span>
        <div role="status" className="ml-auto flex min-w-0 items-center gap-2 text-[11px] text-muted">
          <span className={cx("size-2 flex-none rounded-full", dot)} />
          <span className="min-w-0"><strong className="font-semibold text-soft">{status.error ? "hub unreachable" : s ? `door ${s.you}` : "connecting…"}</strong>
            <small className="block max-w-[34vw] truncate text-[9px] text-faint">{s ? `${location.host} · ${s.home} · read ${status.at?.toLocaleTimeString()}` : status.error}</small></span>
        </div>
      </header>

      <main className="grid min-h-0 grid-cols-1 md:grid-cols-[288px_minmax(0,1fr)]">
        {s ? <Rail s={s} machine={view.machine} setMachine={m => setView(v => ({ ...v, machine: m }))} /> : <aside className="border-r border-line bg-rail"><State error={!!status.error}>{status.error ?? "loading…"}</State></aside>}
        <section className="min-h-0 min-w-0 overflow-y-auto">
          <StatusBar s={s} error={status.error} />
          <nav role="tablist" aria-label="View" className="flex flex-wrap border-b border-line bg-bg px-4 py-3">
            {TABS.map((t, i) => (
              <button key={t} role="tab" type="button" aria-selected={view.tab === t} onClick={() => setView(v => ({ ...v, tab: t }))}
                className={cx("min-h-[34px] border border-line px-4 text-[11px] font-semibold capitalize", i === 0 && "rounded-l-[5px]",
                  i === TABS.length - 1 ? "rounded-r-[5px]" : "border-r-0",
                  view.tab === t ? "border-line-strong bg-accent-dim text-accent-ink" : "bg-raised text-muted hover:text-text")}>
                {t}{t === "jobs" && s?.jobs.running.length ? ` · ${s.jobs.running.length}` : ""}
              </button>
            ))}
          </nav>
          <div hidden={view.tab !== "search"}><SearchView st={view.search} setSt={st => setView(v => ({ ...v, search: st }))} machine={view.machine} focusKey={focusKey} /></div>
          {view.tab === "live" && <LiveView machine={view.machine} on />}
          {view.tab === "jobs" && <JobsView s={s} on />}
          {view.tab === "queries" && <QueriesView on />}
          {view.tab === "compare" && <CompareView on />}
          {view.tab === "store" && (s ? <StoreView s={s} /> : <State>loading…</State>)}
        </section>
      </main>
    </div>
  );
}
