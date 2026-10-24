import { useEffect, useState } from "react";
import { usePoll } from "./api";
import type { Status } from "./types";
import { pill, TopBar, type Theme } from "./components/TopBar";
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
  const machines = s ? Object.keys({ ...s.machines, ...s.versions }).sort() : [];
  return (
    <div className="h-dvh overflow-y-auto">
      <TopBar theme={theme} setTheme={setTheme}
        note={status.error ? "hub unreachable" : s ? `${s.code.name} ${s.code.version} · door ${s.you} · read ${status.at?.toLocaleTimeString()}` : "reading…"}
        link={<a href="#" className={pill}>Glance</a>} />
      <main className="mx-auto max-w-[1200px] px-5 pt-8 pb-20 font-sans">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
          <nav role="tablist" aria-label="View" className="flex flex-wrap gap-1.5">
            {TABS.map(t => (
              <button key={t} role="tab" type="button" aria-selected={view.tab === t} onClick={() => setView(v => ({ ...v, tab: t }))}
                className={cx("rounded-full px-4 py-2 text-[14px] font-semibold capitalize",
                  view.tab === t ? "bg-accent-dim text-accent-ink" : "text-muted hover:bg-panel hover:text-text")}>
                {t}{t === "jobs" && s?.jobs.running.length ? <span className="ml-1.5 rounded-full bg-warning px-1.5 text-[11px] text-bg">{s.jobs.running.length}</span> : null}
              </button>
            ))}
          </nav>
          {machines.length > 0 && (view.tab === "search" || view.tab === "live") && (
            <span className="ml-auto flex items-center gap-2.5 text-[13px] text-muted">Machine
              <Seg label="Machine" value={view.machine} onChange={m => setView(v => ({ ...v, machine: m }))}
                options={[{ value: "", label: "all" }, ...machines.filter(m => !m.endsWith("-import")).map(m => ({ value: m, label: m }))]} />
            </span>
          )}
        </div>
        <span className="mt-3 hidden gap-1 text-[12px] text-faint lg:flex"><Kbd>/</Kbd> search · <Kbd>j</Kbd> <Kbd>k</Kbd> move · <Kbd>↵</Kbd> open · <Kbd>esc</Kbd> close</span>
        {(status.error || (s?.warnings.length ?? 0) > 0) && (
          <div className="mt-4 flex flex-col gap-1.5">
            {status.error && <p className="m-0 rounded-xl border border-danger bg-danger-wash px-4 py-2.5 text-[13px] text-danger">last poll failed: {status.error}</p>}
            {s?.warnings.map(w => <p key={w} className="m-0 rounded-xl border border-warning px-4 py-2.5 text-[13px] text-soft">{w}</p>)}
          </div>
        )}
        <div className="mt-6 overflow-hidden rounded-2xl border border-line bg-bg">
          <div hidden={view.tab !== "search"}><SearchView st={view.search} setSt={st => setView(v => ({ ...v, search: st }))} machine={view.machine} focusKey={focusKey} /></div>
          {view.tab === "live" && <LiveView machine={view.machine} on />}
          {view.tab === "jobs" && <JobsView s={s} on />}
          {view.tab === "queries" && <QueriesView on />}
          {view.tab === "compare" && <CompareView on />}
          {view.tab === "store" && (s ? <StoreView s={s} /> : <State>loading…</State>)}
        </div>
      </main>
    </div>
  );
}
