import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { flushSync } from "react-dom";
import { get, prefetch } from "./api";
import { usePoll } from "./api";
import { ago, bkk, clock } from "./format";
import type { Queries, ShowResult, Status } from "./types";
import { NavDrawer, Palette, Sidebar, TabBar, TopNav, type Layout, type HubState, type PaletteSession, type Theme, type View, VIEWS } from "./components/Shell";
import { Drawer } from "./components/Drawer";
import { Mark, Menu as MenuIcon, Search as SearchIcon } from "./components/Icons";
import { cx, Loading, State } from "./components/ui";
import { Context, SearchView, shortRepo, type SearchState } from "./views/SearchView";
import { Incidents } from "./components/Incidents";
import { GlancePage } from "./views/GlancePage";
// Every view but Home and Search loads on first use, so the first page carries only those two (relic4-scan's
// review, 2026-10-25: "fast"; the main JS had grown to 51.9 KB gz with all ten views in it).
const MemoryView = lazy(() => import("./views/MemoryView").then(m => ({ default: m.MemoryView })));
const MapView = lazy(() => import("./views/MapView").then(m => ({ default: m.MapView })));
const OraclesView = lazy(() => import("./views/OraclesView").then(m => ({ default: m.OraclesView })));
const FamilyView = lazy(() => import("./views/FamilyView").then(m => ({ default: m.FamilyView })));
const ConnectView = lazy(() => import("./views/ConnectView").then(m => ({ default: m.ConnectView })));
const LiveView = lazy(() => import("./views/LiveView").then(m => ({ default: m.LiveView })));
const JobsView = lazy(() => import("./views/JobsView").then(m => ({ default: m.JobsView })));
const QueriesView = lazy(() => import("./views/QueriesView").then(m => ({ default: m.QueriesView })));
const CompareView = lazy(() => import("./views/CompareView").then(m => ({ default: m.CompareView })));
const IncidentsView = lazy(() => import("./views/IncidentsView").then(m => ({ default: m.IncidentsView })));
const PerfView = lazy(() => import("./views/PerfView").then(m => ({ default: m.PerfView })));
const SettingsView = lazy(() => import("./views/SettingsView").then(m => ({ default: m.SettingsView })));
const StoreView = lazy(() => import("./views/StoreView").then(m => ({ default: m.StoreView })));

const TABS = VIEWS.map(v => v.id).filter(v => v !== "home");

/** The URL hash holds the view: #tab=search&q=...&horizon=...&with=...&repo=...&session=...&machine=..., so a view is a
 *  link and back/forward work (relic4-scan src/page/shell.js ?view= deep links). No hash (the hub's root) = Home. */
function readHash(): { view: View; machine: string; search: SearchState } {
  const raw = location.hash.slice(1);
  const h = new URLSearchParams(raw.startsWith("/") ? "" : raw);
  const t = h.get("tab") ?? "";
  const view: View = (TABS as string[]).includes(t) ? (t as View) : "home";
  return { view, machine: h.get("machine") ?? "", search: { q: h.get("q") ?? "", horizon: h.get("horizon") ?? "", with: h.get("with") ?? "", repo: h.get("repo") ?? "", role: h.get("role") ?? "", session: h.get("session") ?? "", home: h.get("home") ?? "" } };
}
function writeHash(view: View, machine: string, s: SearchState) {
  let next = "#";
  if (view !== "home") {
    const h = new URLSearchParams({ tab: view });
    if (machine) h.set("machine", machine);
    if (view === "search" || view === "live") for (const [k, v] of Object.entries(s)) if (v) h.set(k, v);
    // a view's own place in the hash stays (#tab=oracles&oracle=neo-oracle): with the views loading lazily, the
    // shell writes the hash before the view has read it, and a deep link to one oracle fell back to the list
    const was = new URLSearchParams(location.hash.slice(1));
    if (view === "oracles" && was.get("tab") === "oracles" && was.get("oracle")) h.set("oracle", was.get("oracle")!);
    if (view === "map" && was.get("tab") === "map" && was.get("sessions")) h.set("sessions", was.get("sessions")!);
    if (view === "queries" && was.get("tab") === "queries") for (const k of ["pane", "trace", "since", "until"]) if (was.get(k)) h.set(k, was.get(k)!);
    next = "#" + h;
  }
  if (next !== (location.hash || "#")) history.pushState(null, "", next === "#" ? location.pathname : next);
}

export function App() {
  const [st, setSt] = useState(readHash);
  const [theme, setTheme] = useState<Theme>(() => (localStorage.getItem("relic5-theme") as Theme) || "dark");
  const [focusKey, setFocusKey] = useState(0);
  const [layout, setLayoutState] = useState<Layout>(() => (localStorage.getItem("relic5-layout") as Layout) || "top");
  const setLayout = (l: Layout) => { localStorage.setItem("relic5-layout", l); setLayoutState(l); };
  const [palette, setPalette] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const status = usePoll<Status>("/api/status", 15000);
  const queries = usePoll<Queries>("/api/queries", 60000);
  const s = status.data;
  const sess = usePoll<{ sessions: { uuid: string; name?: string | null; repo?: string | null; endedAt?: string }[] }>("/api/sessions?limit=500", 120000);
  const [reading, setReading] = useState<{ x: PaletteSession; r: ShowResult | null; err?: string } | null>(null);
  const openSession = (x: PaletteSession) => {
    setReading({ x, r: null });
    get<ShowResult>(`/api/show?id=${encodeURIComponent(x.sid)}&seq=0&before=0&after=14`)
      .then(r => setReading(v => v && v.x.sid === x.sid ? { x, r } : v)).catch(e => setReading(v => v && v.x.sid === x.sid ? { x, r: null, err: String(e.message ?? e) } : v));
  };

  useEffect(() => { document.documentElement.dataset.theme = theme; localStorage.setItem("relic5-theme", theme); }, [theme]);
  useEffect(() => { writeHash(st.view, st.machine, st.search); }, [st]);
  useEffect(() => {   // when the first page has settled: the Map's points and its three.js, so the Map opens at once
    const idle = (window as Window & { requestIdleCallback?: (f: () => void) => number }).requestIdleCallback ?? ((f: () => void) => setTimeout(f, 2500));
    idle(() => { prefetch("/api/map?limit=3000"); import("./views/Map3D").catch(() => {}); });
  }, []);
  useEffect(() => {
    const pop = () => setSt(readHash());
    const key = (e: KeyboardEvent) => {
      const typing = ["INPUT", "TEXTAREA"].includes((e.target as HTMLElement).tagName);
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette(p => !p); }
      else if (e.key === "/" && !typing) { e.preventDefault(); setSt(v => ({ ...v, view: "search" })); setFocusKey(k => k + 1); }
    };
    window.addEventListener("popstate", pop); window.addEventListener("hashchange", pop); window.addEventListener("keydown", key);
    return () => { window.removeEventListener("popstate", pop); window.removeEventListener("hashchange", pop); window.removeEventListener("keydown", key); };
  }, []);

  // a view change cross-fades (the CSS @view-transition only fires between documents, not on a hash change)
  const shift = (f: () => void) => { const d = document as Document & { startViewTransition?: (cb: () => void) => unknown };
    if (d.startViewTransition && !matchMedia("(prefers-reduced-motion: reduce)").matches) d.startViewTransition(() => flushSync(f)); else f(); };
  const go = (view: View) => { shift(() => setSt(v => ({ ...v, view }))); document.getElementById("main")?.scrollTo({ top: 0 }); };
  const search = (q: string) => { setSt(v => ({ ...v, view: "search", search: { ...v.search, q } })); setFocusKey(k => k + 1); };
  const recent = useMemo(() => [...new Set([...(queries.data?.searches ?? []), ...(queries.data?.last ?? []).filter(r => r.tool === "relic_search")]
    .filter(r => r.query && r.query.length < 60).map(r => r.query.trim()))], [queries.data]);
  const hub: HubState = status.error ? "failed" : !s ? "unknown" : s.warnings.length ? "warning" : "ok";
  const machines = s ? Object.keys({ ...s.machines, ...s.versions }).sort().filter(m => !m.endsWith("-import")) : [];
  const foot = status.error ? <>The hub did not answer.</> : s ? <span title={`relic5 ${s.code.version} · door ${s.you}`}>{s.warnings.length ? `${s.warnings.length} warning${s.warnings.length === 1 ? "" : "s"}, see Home.` : "Every machine is in."} Read {clock(status.at)}.</span> : <>Reading the hub…</>;
  const palSessions: PaletteSession[] = (sess.data?.sessions ?? []).map(x => ({ sid: x.uuid, name: x.name || x.uuid.slice(0, 8), repo: shortRepo(x.repo), ts: x.endedAt ?? "" }));

  return (
    <div className="h-dvh">
      <a href="#main" onClick={e => { e.preventDefault(); document.getElementById("main")?.focus(); }}
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-lg focus:bg-panel focus:px-4 focus:py-3 focus:text-sm">Skip to content</a>
      {layout === "side" && <Sidebar view={st.view} go={go} state={hub} foot={foot} theme={theme} setTheme={setTheme} badges={{ jobs: s?.jobs.running.length }}
        onPalette={() => setPalette(true)} onLayout={() => setLayout("top")} />}
      {/* the drawer on a wide screen sits beside the page and pushes it right: the page stays in view and in use */}
      <div id="main" tabIndex={-1} className={cx("h-dvh overflow-y-auto transition-[padding] duration-200 ease-out focus:outline-none", layout === "side" && "sm:pl-[232px] max-[1100px]:sm:pl-[68px]", drawer && layout !== "side" && "lg:pl-[280px]")}>
        {layout === "top" && <TopNav view={st.view} go={go} state={hub} foot={foot} theme={theme} setTheme={setTheme} badges={{ jobs: s?.jobs.running.length }}
          onPalette={() => setPalette(true)} onLayout={() => setLayout("side")} onDrawer={() => setDrawer(d => !d)} version={s?.code.version} />}
        {/* phone: a slim top bar (mark, state, the palette); the views sit in the bottom bar */}
        <header className="sticky top-0 z-10 flex items-center gap-3 border-b border-line bg-[color-mix(in_srgb,var(--bg)_90%,transparent)] px-4 py-2.5 backdrop-blur sm:hidden">
          <button type="button" onClick={() => setDrawer(true)} aria-label="Open the menu" aria-haspopup="dialog" className="-ml-2 grid size-11 place-items-center rounded-lg text-muted"><MenuIcon size={20} /></button>
          <Mark size={30} /><b className="text-base font-bold text-accent">relic5</b>
          <span className={cx("flex items-center gap-1.5 truncate text-xs font-semibold", hub === "ok" ? "text-ok" : hub === "failed" ? "text-danger" : hub === "warning" ? "text-warning" : "text-muted")}><span className="size-2 rounded-full bg-current" />{hub === "ok" ? "All in" : hub === "failed" ? "Hub unreachable" : hub === "warning" ? `${s?.warnings.length} warning${s?.warnings.length === 1 ? "" : "s"}` : "Reading"} · {clock(status.at)}</span>
          <button type="button" onClick={() => setPalette(true)} aria-label="Search or jump" className="ml-auto grid size-11 place-items-center rounded-lg border border-line text-muted"><SearchIcon size={18} /></button>
        </header>
        <main className="mx-auto max-w-[1600px] px-5 pt-6 pb-28 sm:px-10 sm:pt-10">
          {st.view !== "home" && s?.copy && (
            <p className="m-0 mb-6 rounded-xl border border-line bg-panel px-5 py-3 text-sm text-soft">
              A copy of {s.copy.of}'s hub, as of {bkk(s.copy.at)} Bangkok ({ago(s.copy.at)}, snapshot {s.copy.snapshot}). Search works; nothing new arrives here, so push, backup and seal checks are off.
            </p>
          )}
          {st.view === "home" && <GlancePage s={s} error={status.error} at={status.at} openHub={() => go("live")} search={search} />}
          <div hidden={st.view !== "search"}>
            <SearchView st={st.search} setSt={search2 => setSt(v => ({ ...v, search: search2 }))} machine={st.machine}
              setMachine={m => setSt(v => ({ ...v, machine: m }))} machines={machines} recent={recent} top={queries.data?.top ?? []} sessions={palSessions} focusKey={focusKey} />
          </div>
          <Suspense fallback={<Loading label="Loading the page" />}>
          {st.view === "live" && <LiveView machine={st.machine} role={st.search.role} machines={machines}
            setMachine={m => setSt(v => ({ ...v, machine: m }))} setRole={role => setSt(v => ({ ...v, search: { ...v.search, role } }))} on />}
          {st.view === "memory" && <MemoryView />}
          {st.view === "oracles" && <OraclesView />}
          {st.view === "family" && <FamilyView />}
          {st.view === "map" && <MapView openSession={(sid, name, repo) => openSession({ sid, name, repo, ts: "" })}
            search={(q, session) => setSt(v => ({ ...v, view: "search", search: { ...v.search, q, session: session ?? "" } }))} />}
          {st.view === "connect" && <ConnectView />}
          {st.view === "jobs" && <JobsView s={s} on />}
          {st.view === "queries" && <QueriesView on />}
          {st.view === "compare" && <CompareView on />}
          {st.view === "store" && (s ? <StoreView s={s} /> : <p className="text-muted">Reading the hub…</p>)}
          {st.view === "incidents" && <IncidentsView s={s ?? null} error={status.error} />}
          {st.view === "perf" && <PerfView on />}
          {st.view === "settings" && <SettingsView theme={theme} setTheme={setTheme} layout={layout} setLayout={setLayout} />}
          </Suspense>
        </main>
      </div>
      <TabBar view={st.view} go={go} onMore={() => setPalette(true)} />
      <Incidents s={s ?? null} error={status.error} open={() => go("incidents")} hidden={st.view === "incidents"} />
      <NavDrawer open={drawer} onClose={() => setDrawer(false)} view={st.view} go={go} state={hub} foot={foot} badges={{ jobs: s?.jobs.running.length }} onPalette={() => setPalette(true)} />
      <Palette open={palette} onClose={() => setPalette(false)} go={go} search={search} recent={recent} sessions={palSessions} openSession={openSession} />
      <Drawer open={!!reading} onClose={() => setReading(null)} title={reading ? <>{reading.x.repo} · {reading.x.name}</> : ""}
        note={reading ? `relic5://session/${reading.x.sid} · the first messages` : ""} onCopy={() => reading && navigator.clipboard.writeText(`relic5://session/${reading.x.sid}`)}>
        {reading?.err ? <State error>{reading.err}</State> : reading?.r ? <Context r={reading.r} q="" /> : <Loading label="Reading the session" />}
      </Drawer>
    </div>
  );
}
