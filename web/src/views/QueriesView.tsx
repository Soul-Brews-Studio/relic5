// Asked: who asked the hub what, and what came of it (Nat, 2026-10-24: "when each search and we store the result then
// can we create a new job to link to that search too? and can we support the trace and trace chained trace log?").
// Four panes: Overview (charts from GET /api/asked), Log (the whole query log, paged, GET /api/access), Chains (each
// search with the hits opened from it and the searches after it, GET /api/trace) and Saved (searches kept as jobs that
// re-run and say what is new, GET/POST /api/saved). The pane and the open chain live in the hash, so a chain is a link.
import { useEffect, useMemo, useState } from "react";
import { post, usePoll } from "../api";
import { bkk, num, shortRepo } from "../format";
import { DataTable, type Col } from "../components/DataTable";
import { Btn, Chip, cx, Hint, inputCls, Lbl, Loading, PageHead, SectionHead, Seg, Stat, State, Stats } from "../components/ui";
import { HourBars, Latency } from "../components/AskedCharts";
import type { AccessPage, AskedStats, ChainRow, Queries, QueryRow, SavedSearch, TraceChain, TraceStep } from "../types";

type Pane = "overview" | "log" | "chains" | "saved";

function hashGet(k: string) { return new URLSearchParams(location.hash.slice(1)).get(k) ?? ""; }
function hashSet(p: Record<string, string>) {
  const h = new URLSearchParams(location.hash.slice(1));
  for (const [k, v] of Object.entries(p)) { if (v) h.set(k, v); else h.delete(k); }
  history.replaceState(null, "", "#" + h);
}
/** Open a search in the Search view (the hash is the Search view's state; App listens to hashchange). */
function openSearch(args: Record<string, unknown>) {
  const h = new URLSearchParams({ tab: "search" });
  for (const k of ["horizon", "with", "repo", "role", "session"]) if (args[k]) h.set(k, String(args[k]));
  h.set("q", String(args.query ?? ""));
  location.hash = h.toString();
}

const short = (c?: string | null) => (c ?? "").replace(/ \((mcp|http)\)$/, "");
const TOOL: Record<string, string> = { relic_found: "found", relic_search: "search", relic_show: "opened", relic_session: "session", relic_sessions: "sessions", relic_trace: "trace", relic_saved: "saved", relic_status: "status" };

function Bars({ rows, label }: { rows: { k: string; n: number }[]; label: string }) {
  const max = Math.max(1, ...rows.map(r => r.n));
  return (
    <div className="min-w-0">
      <Lbl>{label}</Lbl>
      <div className="mt-3 flex flex-col gap-2">{rows.slice(0, 8).map(r => (
        <div key={r.k} className="grid grid-cols-[minmax(0,10rem)_1fr_3.5rem] items-center gap-3 text-sm" title={`${r.k}: ${r.n}`}>
          <span className="truncate text-soft">{r.k}</span>
          <span className="h-2 rounded-full bg-raised"><span className="block h-2 rounded-full bg-accent" style={{ width: `${Math.max(2, (100 * r.n) / max)}%` }} /></span>
          <span className="text-right font-mono text-xs text-muted tabular-nums">{num(r.n)}</span>
        </div>))}</div>
    </div>
  );
}

function Overview({ on, q }: { on: boolean; q: Queries | null }) {
  const [hours, setHours] = useState("24");
  const p = usePoll<AskedStats>(`/api/asked?hours=${hours}`, 30000, on);
  if (p.error && !p.data) return <State error>{p.error}</State>;
  if (!p.data) return <Loading label="Reading the query log" />;
  const s = p.data, last = s.hours[s.hours.length - 1];
  return (
    <>
      <Stats>
        <Stat label="running now" value={q?.running.length ?? 0} tone={q?.running.length ? "live" : undefined} />
        <Stat label={`calls · ${hours} h`} value={num(s.calls)} note={`${num(s.searches)} searches`} />
        <Stat label="last hour" value={num(last?.n ?? 0)} note={last ? `p50 ${last.p50_ms ?? "–"} ms · p95 ${last.p95_ms ?? "–"} ms` : undefined} />
        <Stat label="zero-hit share" value={s.zero_share == null ? "–" : `${Math.round(s.zero_share * 1000) / 10}%`} tone={s.zero ? "warn" : undefined} note={`${s.zero} of ${s.searches} searches`} />
      </Stats>
      <div className="mb-4 flex"><Seg label="Window" value={hours} onChange={setHours} options={[{ value: "24", label: "24 h" }, { value: "72", label: "3 days" }, { value: "168", label: "a week" }]} /></div>
      <section className="grid gap-8 rounded-2xl border border-line bg-panel p-5 lg:grid-cols-2">
        <HourBars s={s} />
        <Latency s={s} />
      </section>
      <section className="mt-5 grid gap-8 rounded-2xl border border-line bg-panel p-5 md:grid-cols-2">
        <Bars label="by client" rows={s.by_client.map(r => ({ k: r.client, n: r.n }))} />
        <Bars label="by tool" rows={s.by_tool.map(r => ({ k: TOOL[r.tool] ?? r.tool, n: r.n }))} />
      </section>
      {q && <>
        <SectionHead sub="The same words searched more than once: candidates for a saved search.">Asked more than once</SectionHead>
        <DataTable rows={q.top} rowKey={r => r.query} onRow={r => openSearch({ query: r.query })}
          cols={[{ key: "q", head: "query", lead: true, cell: r => r.query }, { key: "n", head: "times", num: true, cell: r => r.n }]} />
        <SectionHead sub="What search still misses. Open one to try other words.">Zero hits</SectionHead>
        <DataTable rows={q.zero_hits} rowKey={(r, i) => r.at + i} onRow={r => openSearch({ query: r.query })} empty="none: every query found something"
          cols={[{ key: "at", head: "at (+07)", cell: r => <time>{bkk(r.at)}</time> }, { key: "q", head: "query", lead: true, cell: r => r.query }]} />
      </>}
    </>
  );
}

// ---- the log ---------------------------------------------------------------------------------------------------

function Log({ on, openChain }: { on: boolean; openChain: (id: string) => void }) {
  const [tool, setTool] = useState(""), [text, setText] = useState(""), [q, setQ] = useState(""), [only, setOnly] = useState("");
  const [pages, setPages] = useState<number[]>([]);    // the stack of `before` cursors: Older pushes, Newer pops
  const before = pages[pages.length - 1];
  useEffect(() => { const t = setTimeout(() => setQ(text.trim()), 250); return () => clearTimeout(t); }, [text]);
  useEffect(() => setPages([]), [tool, q, only]);
  const params = new URLSearchParams({ limit: "50", ...(before != null ? { before: String(before) } : {}), ...(tool ? { tool } : {}), ...(q ? { q } : {}), ...(only ? { [only]: "1" } : {}) });
  const p = usePoll<AccessPage>(`/api/access?${params}`, before == null ? 15000 : 0, on);
  const cols: Col<QueryRow>[] = [
    { key: "at", head: "at (+07)", w: "w-32", cell: r => <time>{bkk(r.at)}</time> },
    { key: "c", head: "client", w: "w-44", meta: true, cell: r => <span className="truncate" title={r.client}>{short(r.client) || <Chip>{r.door}</Chip>}</span> },
    { key: "t", head: "tool", w: "w-24", cell: r => TOOL[r.tool] ?? r.tool },
    { key: "q", head: "query or id", lead: true, cell: r => <span className="break-all">{r.query}</span>, title: r => r.query },
    { key: "h", head: "hits", num: true, w: "w-16", cell: r => r.hits == null ? "" : r.hits === 0 ? <Chip tone="warn">0</Chip> : r.hits },
    { key: "ms", head: "ms", num: true, w: "w-20", cell: r => r.ms ?? "" },
    { key: "e", head: "", w: "w-24", cell: r => r.error ? <Chip tone="bad" title={r.error}>error</Chip> : r.parent ? <Chip tone="live" title={`follows ${r.parent}`}>chained</Chip> : "" },
  ];
  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <input type="search" value={text} onChange={e => setText(e.target.value)} placeholder="Filter by words in the query" aria-label="Filter the log by query" className={inputCls + " w-full sm:w-72"} />
        <Seg label="Tool" value={tool} onChange={setTool} options={[{ value: "", label: "every tool" }, { value: "relic_search", label: "search" }, { value: "relic_show", label: "opened" }, { value: "relic_session", label: "session" }]} />
        <Seg label="Only" value={only} onChange={setOnly} options={[{ value: "", label: "all" }, { value: "zero", label: "zero hits" }, { value: "errors", label: "errors" }]} />
      </div>
      {p.error && !p.data ? <State error>{p.error}</State> : !p.data ? <Loading label="Reading the log" /> : <>
        <DataTable rows={p.data.rows} rowKey={r => String(r.n)} cols={cols} empty="no call matches"
          onRow={r => (r.id ? openChain(r.id) : undefined)} />
        <div className="mt-4 flex items-center gap-3">
          <Btn disabled={!pages.length} onClick={() => setPages(pages.slice(0, -1))}>Newer</Btn>
          <Btn disabled={p.data.next_before == null} onClick={() => setPages([...pages, p.data!.next_before!])}>Older</Btn>
          <span className="text-sm text-muted">{num(p.data.total)} calls in the log · a row with an id opens its chain</span>
        </div>
      </>}
    </>
  );
}

// ---- chains ----------------------------------------------------------------------------------------------------

function Step({ s, onSave }: { s: TraceStep; onSave: (s: TraceStep) => void }) {
  const search = s.tool === "relic_search";
  if (s.tool === "relic_found") {
    const a = (s.args ?? {}) as { goal?: string; how?: string; found?: string; links?: string[] };
    return (
      <li className="relative pb-5 pl-6" style={{ marginLeft: `${Math.min(s.depth, 6) * 1.5}rem` }}>
        <span className="absolute top-1.5 left-0 size-2.5 rounded-full bg-ok" aria-hidden />
        <div className="rounded-xl bg-ok-wash px-4 py-3">
          <div className="flex flex-wrap items-baseline gap-x-3"><span className="text-xs font-bold tracking-[0.12em] text-ok uppercase">found</span><b className="min-w-0 break-words text-text">{a.found}</b></div>
          <dl className="m-0 mt-2 grid grid-cols-[5rem_minmax(0,1fr)] gap-x-3 gap-y-1 text-sm">
            <dt className="text-muted">looked for</dt><dd className="m-0 break-words text-soft">{a.goal}</dd>
            {a.how && <><dt className="text-muted">how</dt><dd className="m-0 break-words text-soft">{a.how}</dd></>}
            {!!a.links?.length && <><dt className="text-muted">links</dt><dd className="m-0 flex flex-col font-mono text-xs break-all text-accent">{a.links.map(l => <span key={l}>{l}</span>)}</dd></>}
          </dl>
          <div className="mt-2 font-mono text-xs text-faint"><time>{bkk(s.at)}</time> · {short(s.client) || s.door} · #{s.id}</div>
        </div>
      </li>
    );
  }
  return (
    <li className="relative pb-5 pl-6" style={{ marginLeft: `${Math.min(s.depth, 6) * 1.5}rem` }}>
      <span className={cx("absolute top-1.5 left-0 size-2.5 rounded-full", search ? "bg-accent" : "border-2 border-amber bg-bg")} aria-hidden />
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-xs font-bold tracking-[0.12em] text-muted uppercase">{TOOL[s.tool] ?? s.tool}</span>
        <span className={cx("min-w-0 break-all", search ? "font-semibold text-text" : "font-mono text-sm text-soft")}>{s.query || s.id}</span>
        {s.hits != null && (s.hits === 0 ? <Chip tone="warn">0 hits</Chip> : <Chip>{s.hits} hits</Chip>)}
        {s.error && <Chip tone="bad" title={s.error}>error</Chip>}
      </div>
      <div className="mt-1 flex flex-wrap gap-x-3 font-mono text-xs text-faint">
        <time>{bkk(s.at)}</time><span>{short(s.client) || s.door}</span>{s.ms != null && <span>{s.ms} ms</span>}<span title="trace id: pass it as parent">#{s.id}</span>
      </div>
      {search && (
        <div className="mt-2 flex flex-wrap gap-2">
          <Btn onClick={() => openSearch(s.args ?? { query: s.query })}>Run again</Btn>
          <Btn onClick={() => onSave(s)}>Save as a job</Btn>
        </div>
      )}
      {search && !!s.top?.length && (
        <ol className="mt-3 flex list-none flex-col gap-1 p-0">{s.top.map((h, i) => (
          <li key={h.link + i} className="flex min-w-0 items-baseline gap-2 text-sm">
            <span className="w-5 flex-none text-right font-mono text-xs text-faint">{i + 1}</span>
            <button type="button" onClick={() => openSearch({ ...(s.args ?? {}), query: s.query, session: (h.session ?? "").slice(0, 8) })}
              className="min-w-0 truncate text-left text-accent hover:underline" title={`${h.repo ?? ""}\n${h.link}`}>{shortRepo(h.repo)} · {(h.session ?? "").slice(0, 8)}</button>
            <span className="flex-none font-mono text-xs text-faint">{h.role} · {bkk(h.ts)}</span>
          </li>))}</ol>
      )}
    </li>
  );
}

function Chain({ id, close, onSave }: { id: string; close: () => void; onSave: (s: TraceStep) => void }) {
  const p = usePoll<TraceChain>(`/api/trace?id=${encodeURIComponent(id)}`, 20000);
  if (p.error && !p.data) return <State error>{p.error}</State>;
  if (!p.data) return <Loading label="Reading the chain" />;
  const c = p.data;
  return (
    <section className="rounded-2xl border border-line bg-panel p-5">
      <div className="mb-4 flex flex-wrap items-baseline gap-3">
        <button type="button" onClick={close} className="min-h-11 rounded-lg px-2 text-sm font-semibold text-accent">← All chains</button>
        <h2 className="m-0 text-base font-bold text-text">Chain #{c.root}</h2>
        <span className="text-sm text-muted">{c.steps.length} steps · {c.searches} searches · {c.opened} opened · {bkk(c.first)} → {bkk(c.last)}</span>
        {c.found.length > 0 ? <Chip tone="ok">found</Chip> : <Chip>no answer noted</Chip>}
      </div>
      <ol className="m-0 list-none border-l border-line p-0 pl-1">{c.steps.map(s => <Step key={s.id} s={s} onSave={onSave} />)}</ol>
      <Hint>GET /api/trace?id={c.id} · MCP relic_trace {"{"}"id": "{c.id}"{"}"}</Hint>
    </section>
  );
}

function Chains({ on, open, setOpen, onSave }: { on: boolean; open: string; setOpen: (id: string) => void; onSave: (s: TraceStep) => void }) {
  const p = usePoll<{ chains: ChainRow[] }>("/api/trace?limit=60", 20000, on && !open);
  if (open) return <Chain id={open} close={() => setOpen("")} onSave={onSave} />;
  if (p.error && !p.data) return <State error>{p.error}</State>;
  if (!p.data) return <Loading label="Reading the chains" />;
  const cols: Col<ChainRow>[] = [
    { key: "l", head: "last (+07)", w: "w-32", cell: r => <time>{bkk(r.last)}</time> },
    { key: "q", head: "looked for", lead: true, cell: r => (
      <span className="min-w-0">
        <span className="block truncate">{r.goal ?? r.query ?? <span className="font-mono text-muted">#{r.root}</span>}</span>
        {r.found && <span className="block truncate text-xs text-ok">found: {r.found}</span>}
      </span>) },
    { key: "s", head: "steps", num: true, w: "w-16", cell: r => r.steps },
    { key: "se", head: "searches", num: true, w: "w-20", cell: r => r.searches },
    { key: "o", head: "opened", num: true, w: "w-20", cell: r => r.opened },
    { key: "c", head: "client", w: "w-44", meta: true, cell: r => <span className="truncate">{r.clients.map(short).join(", ")}</span> },
  ];
  return (
    <>
      <p className="m-0 mb-4 max-w-[75ch] text-sm text-muted">A chain is a search and what followed from it: the hits opened, the narrower searches, the saved-search runs.
        A tool call joins a chain when it passes <code className="font-mono text-code">parent</code> = the <code className="font-mono text-code">trace.id</code> of the call before it; the Search page does that for you.
        An agent closes a chain with <code className="font-mono text-code">relic_found</code>: what it looked for, how it searched, and what it found (the MCP server asks every agent to).</p>
      <DataTable rows={p.data.chains} rowKey={r => r.root} cols={cols} onRow={r => setOpen(r.root)} empty="no chains yet: search, then open a hit" />
    </>
  );
}

// ---- saved searches --------------------------------------------------------------------------------------------

function Saved({ on, bump }: { on: boolean; bump: number }) {
  const p = usePoll<{ saved: SavedSearch[] }>(`/api/saved?b=${bump}`, 30000, on);
  const [busy, setBusy] = useState(""), [err, setErr] = useState<string | null>(null);
  const act = async (body: Record<string, unknown>) => {
    setBusy(String(body.id)); setErr(null);
    try { await post("/api/saved", body); p.reload(); } catch (e) { setErr(String((e as Error).message)); } finally { setBusy(""); }
  };
  if (p.error && !p.data) return <State error>{p.error}</State>;
  if (!p.data) return <Loading label="Reading the saved searches" />;
  return (
    <>
      <p className="m-0 mb-4 max-w-[75ch] text-sm text-muted">A saved search is a job: the hub runs it again on its own (every hour unless set) and puts each run in the chain of the search it came from. New hits since the last run show here and on the Jobs page.</p>
      {err && <State error>{err}</State>}
      {!p.data.saved.length ? <State>No saved searches yet. Open a chain and press “Save as a job” on a search, or call MCP relic_saved {"{"}"action": "add", "from": "&lt;trace.id&gt;"{"}"}.</State> :
        <div className="flex flex-col gap-3">{p.data.saved.map(s => (
          <article key={s.id} className="rounded-2xl border border-line bg-panel p-5">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <h3 className="m-0 min-w-0 text-base font-bold break-words text-text">{s.name}</h3>
              {s.last_new ? <Chip tone="live">{s.last_new} new</Chip> : null}
              {s.last_error && <Chip tone="bad" title={s.last_error}>failed</Chip>}
              <span className="ml-auto font-mono text-xs text-faint">#{s.id}</span>
            </div>
            <div className="mt-1 text-sm text-muted">
              every {s.every} min · {s.runs} runs · last {s.last_run ? bkk(s.last_run) : "not yet"}{s.last_hits != null && ` · ${s.last_hits} hits`} · {s.seen} hits seen
              {Object.keys(s.args).filter(k => k !== "query").length > 0 && ` · ${Object.entries(s.args).filter(([k]) => k !== "query").map(([k, v]) => `${k} ${v}`).join(", ")}`}
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <Btn disabled={busy === s.id} onClick={() => act({ action: "run", id: s.id })}>{busy === s.id ? "Running…" : "Run now"}</Btn>
              <Btn onClick={() => openSearch(s.args)}>Open in Search</Btn>
              {(s.from || s.last_record) && <Btn onClick={() => { hashSet({ pane: "chains", trace: (s.from || s.last_record)! }); dispatchEvent(new HashChangeEvent("hashchange")); }}>Its chain</Btn>}
              <Btn disabled={busy === s.id} onClick={() => confirm(`Stop the saved search "${s.name}"?`) && act({ action: "remove", id: s.id })}>Remove</Btn>
            </div>
          </article>))}</div>}
    </>
  );
}

export function QueriesView({ on }: { on: boolean }) {
  const [pane, setPane] = useState<Pane>(() => (["overview", "log", "chains", "saved"].includes(hashGet("pane")) ? hashGet("pane") as Pane : hashGet("trace") ? "chains" : "overview"));
  const [open, setOpen] = useState(hashGet("trace"));
  const [bump, setBump] = useState(0), [note, setNote] = useState<string | null>(null);
  const q = usePoll<Queries>("/api/queries", 30000, on && pane === "overview");
  useEffect(() => { hashSet({ pane: pane === "overview" ? "" : pane, trace: pane === "chains" ? open : "" }); }, [pane, open]);
  useEffect(() => {
    const pop = () => { const t = hashGet("trace"), pn = hashGet("pane"); if (t) { setOpen(t); setPane("chains"); } else if (pn) setPane(pn as Pane); };
    addEventListener("hashchange", pop);
    return () => removeEventListener("hashchange", pop);
  }, []);
  const openChain = (id: string) => { setOpen(id); setPane("chains"); };
  const save = async (s: TraceStep) => {
    const every = prompt(`Run "${s.query}" again every how many minutes?`, "60");
    if (!every) return;
    try { await post("/api/saved", { action: "add", from: s.id, every: Number(every) }); setBump(b => b + 1); setNote(`Saved "${s.query}" as a job, every ${every} min.`); }
    catch (e) { setNote(String((e as Error).message)); }
  };
  const tabs = useMemo(() => [{ value: "overview", label: "Overview" }, { value: "log", label: "Log" }, { value: "chains", label: "Chains" }, { value: "saved", label: "Saved" }], []);
  return (
    <>
      <PageHead title="Asked" sub="Who asked the hub what, how fast it answered, and what followed: each search is kept with its hits, chained to what was opened after it, and can be saved as a job.">
        <Seg label="Pane" value={pane} onChange={v => setPane(v as Pane)} options={tabs} />
      </PageHead>
      {note && <div role="status" className="mb-4 flex items-center gap-3 rounded-xl bg-accent-wash px-4 py-3 text-sm text-accent-ink">{note}<button type="button" className="ml-auto min-h-11 px-2 font-semibold text-accent" onClick={() => setNote(null)}>OK</button></div>}
      {pane === "overview" && <Overview on={on} q={q.data} />}
      {pane === "log" && <Log on={on} openChain={openChain} />}
      {pane === "chains" && <Chains on={on} open={open} setOpen={setOpen} onSave={save} />}
      {pane === "saved" && <Saved on={on} bump={bump} />}
      <div className="mt-8"><Hint>GET /api/asked · /api/access · /api/trace · /api/saved · MCP relic_trace, relic_saved · logs/queries.jsonl on the hub only (0600), never in git</Hint></div>
    </>
  );
}
