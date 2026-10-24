// Search (Nat, 2026-10-24: "left suggest, right search", then "tell the right", then a /oracle-prism + /hallmark redesign).
// The query bar and ONE scope row (what, when, who, machine, repo) sit across the top, the same on a phone and a desktop.
// Before a search the page suggests: what was searched lately, what is asked most, the repos busy this week. After a
// search: on the left the sessions and repos the hits come from; in the middle the hits; on a wide screen a reader on the right that shows the selected hit in its conversation (ARRA Oracle v3's OracleDig list + detail pane:
// the first hit is selected, so the pane is never empty). Narrower screens open the same reader as a drawer.
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { get } from "../api";
import { ago, bkk, repoColor } from "../format";
import type { Hit, SearchResult, ShowResult } from "../types";
import { Drawer } from "../components/Drawer";
import { Markdown } from "../components/Markdown";
import { Btn, Chip, cx, inputCls, Kbd, Lbl, Loading, Marked, Seg, State, Who } from "../components/ui";
import type { PaletteSession } from "../components/Shell";
import { Close, Filter, Search, Session } from "../components/Icons";

export interface SearchState { q: string; horizon: string; with: string; repo: string; role: string; session: string }

/** "-opt-Code-github-com-laris-co-neo-oracle-wt-garage-home-neo-issue190-24oct-sat2026" -> "laris-co-neo-oracle": the
 *  host's path prefix and a worktree's "-wt-<slug>" go; the session title already says what the worktree was for. */
export const shortRepo = (k?: string | null) => (k ?? "").replace(/^-(opt-Code|Users-[^-]+(-Code)?|home-[^-]+(-Code)?)-github-com-/, "")
  .replace(/^git:github\.com\//, "").replace(/-wt-.*$/, "").replace(/--claude-worktrees-.*$/, "") || "(no repo)";
const LAYERS = [
  { value: "", label: "Talk", note: "what people and agents said to each other" },
  { value: "tools", label: "Talk + tools", note: "also the commands agents ran and their output" },
  { value: "thinking", label: "Talk + thinking", note: "also the agents' reasoning" },
  { value: "memory", label: "Memory notes", note: "rules, decisions, references" },
  { value: "git", label: "Git commits", note: "every repo, back to 2025-03" },
  { value: "all", label: "Everything", note: "all of the above" },
];

/** A snippet without the Markdown marks it was cut from (Nat's screenshot: "**" and "#" in every row). */
const clean = (t: string) => t.replace(/\*\*|__|`+/g, "").replace(/^#{1,4}\s+/gm, "").replace(/<\/?pasted_content[^>]*>/g, "")
  .replace(/\|?(\s*:?-{3,}:?\s*\|)+/g, " ").replace(/\s*\|\s*/g, " · ").replace(/(\s·\s)+/g, " · ");

/** Hits that follow each other in one session fold under the first (Panel A: seven rows of one session buried the rest). */
interface Row { h: Hit; i: number; more: Hit[] }
function fold(hits: Hit[]): Row[] {
  const out: Row[] = [];
  hits.forEach((h, i) => {
    const last = out[out.length - 1];
    if (last && h.layer === last.h.layer && h.session_uuid === last.h.session_uuid && h.layer !== "memory" && h.layer !== "git") last.more.push(h);
    else out.push({ h, i, more: [] });
  });
  return out;
}

function HitRow({ h, q, active, onOpen, more, onMore }: { h: Hit; q: string; active: boolean; onOpen: () => void; more?: number; onMore?: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { if (active) ref.current?.scrollIntoView({ block: "nearest" }); }, [active]);
  const where = h.layer === "memory" || h.layer === "git" ? h.title : h.session_name || h.title;
  return (
    <div ref={ref} className={cx("rounded-xl transition-colors duration-[120ms]", active ? "bg-raised" : "hover:bg-panel")}>
      <button type="button" onClick={onOpen} aria-current={active || undefined} className="block w-full px-5 pt-4 pb-3 text-left">
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
          <time className="tabular-nums text-soft">{bkk(h.ts)}</time>
          {h.layer === "memory" ? <Chip tone="ok">{h.role.replace("memory-", "")} note</Chip> : h.layer === "git" ? <Chip tone="ok">{h.role === "commit-claude" ? "commit · Claude" : h.role === "commit-codex" ? "commit · Codex" : "commit"}</Chip> : <><Who role={h.role} />{h.layer !== "prose" && <Chip>{h.layer}</Chip>}</>}
          <span title={`held by ${h.machines.join(", ")}`}>{h.machines.length > 1 ? `on ${h.machines.join(" + ")}` : h.machines[0]}</span>
        </span>
        <span className="mt-1.5 flex min-w-0 items-center gap-2 text-sm font-semibold text-text">
          <span className="size-2 flex-none rounded-full" style={{ background: repoColor(shortRepo(h.repo_key)) }} />
          <span className="truncate"><span style={{ color: repoColor(shortRepo(h.repo_key)) }}>{shortRepo(h.repo_key)}</span>{where ? <> · {where}</> : null}</span>
        </span>
        <span className="mt-1.5 line-clamp-3 block max-w-[78ch] text-sm leading-[1.65] break-words whitespace-pre-wrap text-soft"><Marked text={clean(h.text_snippet)} q={q} /></span>
      </button>
      {!!more && <button type="button" onClick={onMore} className="mb-2 ml-3 inline-flex min-h-9 items-center rounded-lg px-2 text-xs font-semibold text-accent hover:bg-raised">+{more} more in this session</button>}
    </div>
  );
}

/** The message and its neighbours (relic_show), in the reader pane or the drawer. */
export function Context({ r, q }: { r: ShowResult; q: string }) {
  const one = (m: ShowResult["target"], target = false) => (
    <div key={m.ts + m.role + (target ? "t" : "")} className={cx("rounded-xl px-5 py-3", target && "bg-amber-wash")}>
      <div className="flex gap-3 text-xs text-muted"><time className="tabular-nums">{bkk(m.ts)}</time><Who role={m.role} /><span>{(m.machines ?? []).join(", ")}</span></div>
      <div className="mt-1.5 max-w-[80ch] break-words"><Markdown text={m.text ?? ""} q={q} compact /></div>
    </div>
  );
  return <div className="flex flex-col gap-1 px-3 py-3">{r.before.map(m => one(m))}{one(r.target, true)}{r.after.map(m => one(m))}</div>;
}

/** Human / assistant as two toggles, both on by default; at least one stays on. Both on = no role filter. */
export function WhoPick({ role, onChange }: { role: string; onChange: (role: string) => void }) {
  return <Seg label="Who" value={role} onChange={onChange} options={[{ value: "", label: "everyone" }, { value: "user", label: "human" }, { value: "assistant", label: "assistant" }]} />;
}

function RailGroup({ label, children, aside }: { label: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="border-t border-line pt-5 first:border-t-0 first:pt-0">
      <div className="mb-3 flex min-h-6 items-center justify-between"><Lbl>{label}</Lbl>{aside}</div>
      {children}
    </div>
  );
}
const linkBtn = "-my-2.5 inline-flex min-h-11 items-center rounded-lg px-2 text-xs font-semibold text-accent hover:bg-raised";

/** The sessions and repos the current hits come from, most hits first: the left pane's suggestions. */
function Related({ hits, st, narrow }: { hits: Hit[]; st: SearchState; narrow: (p: Partial<SearchState>) => void }) {
  const sessions = useMemo(() => {
    const m = new Map<string, { sid: string; name: string; repo: string; n: number; ts: string }>();
    for (const h of hits) {
      if (h.layer === "memory" || h.layer === "git") continue;
      const e = m.get(h.session_uuid) ?? { sid: h.session_uuid, name: h.session_name || h.title || h.session_uuid.slice(0, 8), repo: shortRepo(h.repo_key), n: 0, ts: h.ts };
      e.n++; if (h.ts > e.ts) e.ts = h.ts; m.set(h.session_uuid, e);
    }
    return [...m.values()].sort((a, b) => b.n - a.n || b.ts.localeCompare(a.ts)).slice(0, 8);
  }, [hits]);
  const repos = useMemo(() => {
    const m = new Map<string, number>();
    for (const h of hits) m.set(shortRepo(h.repo_key), (m.get(shortRepo(h.repo_key)) ?? 0) + 1);
    return [...m.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6);
  }, [hits]);
  if (!sessions.length && !repos.length) return null;
  return <>
    {sessions.length > 0 && (
      <RailGroup label="Sessions" aside={st.session ? <button type="button" onClick={() => narrow({ session: "" })} className={linkBtn}>all sessions</button> : undefined}>
        <ul className="m-0 flex list-none flex-col gap-1 p-0">
          {sessions.map(x => {
            const on = !!st.session && x.sid.startsWith(st.session);
            return (
              <li key={x.sid}>
                <button type="button" onClick={() => narrow({ session: on ? "" : x.sid.slice(0, 8) })} title={x.sid} aria-pressed={on}
                  className={cx("flex min-h-11 w-full items-start gap-2.5 rounded-lg border px-2.5 py-2 text-left transition-colors", on ? "border-accent bg-accent-wash" : "border-transparent hover:bg-panel")}>
                  <span className="mt-0.5 flex-none" style={{ color: repoColor(x.repo) }}><Session size={16} /></span>
                  <span className="min-w-0 flex-1">
                    <span className="line-clamp-2 block text-sm leading-snug text-text">{x.name}</span>
                    <span className="mt-0.5 block truncate text-xs text-muted">{x.repo} · {ago(x.ts)}</span>
                  </span>
                  <span className="font-mono text-xs text-muted tabular-nums">{x.n}</span>
                </button>
              </li>
            );
          })}
        </ul>
      </RailGroup>
    )}
    {repos.length > 1 && (
      <RailGroup label="Repos">
        <ul className="m-0 flex list-none flex-col gap-0.5 p-0">
          {repos.map(([r, n]) => {
            const on = st.repo === r;
            return (
              <li key={r}><button type="button" aria-pressed={on} onClick={() => narrow({ repo: on ? "" : r })}
                className={cx("flex min-h-10 w-full items-center gap-2.5 rounded-lg border px-2.5 text-left text-sm transition-colors", on ? "border-accent bg-accent-wash text-text" : "border-transparent text-soft hover:bg-panel hover:text-text")}>
                <span className="size-2 flex-none rounded-full" style={{ background: repoColor(r) }} />
                <span className="min-w-0 flex-1 truncate" title={r}>{r}</span>
                <span className="font-mono text-xs text-muted tabular-nums">{n}</span>
              </button></li>
            );
          })}
        </ul>
      </RailGroup>
    )}
  </>;
}

/** The same search as an agent would call it (ARRA Oracle v3: the filters shown as the endpoint they become). */
function AsCall({ st }: { st: SearchState }) {
  const [copied, setCopied] = useState(false);
  const args = Object.fromEntries(Object.entries({ query: st.q, with: st.with, horizon: st.horizon, repo: st.repo, role: st.role, session: st.session }).filter(([, v]) => v));
  const call = `relic_search ${JSON.stringify(args)}`;
  return (
    <RailGroup label="As an agent asks it" aside={<button type="button" className={linkBtn} onClick={() => { navigator.clipboard.writeText(call); setCopied(true); setTimeout(() => setCopied(false), 1500); }}>{copied ? "copied" : "copy"}</button>}>
      <code className="block rounded-lg bg-deep px-3 py-2.5 font-mono text-xs leading-relaxed break-all text-soft">{call}</code>
    </RailGroup>
  );
}

const HORIZONS = [{ value: "", label: "auto" }, { value: "7d", label: "7 days" }, { value: "15d", label: "15 days" },
  { value: "1m", label: "month" }, { value: "3m", label: "3 months" }, { value: "archive", label: "all time" }];
const row = "flex min-h-11 w-full items-center gap-3 rounded-lg px-3 text-left text-sm text-soft transition-colors duration-[120ms] hover:bg-panel hover:text-text";

/** Before the first search: suggestions, not filters (prism: the empty page was five filter groups and no suggestion). */
function Launch({ recent, top, repos, when, pick, scopeRepo, layer }: {
  recent: string[]; top: { query: string; n: number }[]; repos: [string, number][]; when: string;
  pick: (q: string) => void; scopeRepo: (r: string) => void; layer: (w: string) => void;
}) {
  const lately = recent.slice(0, 8);
  const most = top.filter(t => t.query && t.query.length < 70).slice(0, 8);
  return (
    <div className="rise grid gap-10 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
      <div className="flex flex-col gap-8">
        <section aria-labelledby="s-lately">
          <h2 id="s-lately" className="m-0 mb-2 px-3 text-sm font-bold text-text">Searched lately</h2>
          {lately.length ? <ul className="m-0 flex list-none flex-col p-0">{lately.map(q => (
            <li key={q}><button type="button" onClick={() => pick(q)} className={row}>
              <span className="flex-none text-faint"><Search size={16} /></span><span className="min-w-0 flex-1 truncate">{q}</span>
            </button></li>))}</ul>
            : <p className="m-0 px-3 text-sm text-muted">Nothing searched yet. What you search shows up here.</p>}
        </section>
        {most.length > 0 && <section aria-labelledby="s-most">
          <h2 id="s-most" className="m-0 mb-2 px-3 text-sm font-bold text-text">Asked most</h2>
          <ul className="m-0 flex list-none flex-col p-0">{most.map(t => (
            <li key={t.query}><button type="button" onClick={() => pick(t.query)} className={row}>
              <span className="min-w-0 flex-1 truncate">{t.query}</span>
              <span className="font-mono text-xs text-faint tabular-nums" title={`asked ${t.n} times`}>{t.n}×</span>
            </button></li>))}</ul>
        </section>}
      </div>
      <div className="flex flex-col gap-8">
        {repos.length > 0 && <section aria-labelledby="s-repos">
          <h2 id="s-repos" className="m-0 mb-1 px-3 text-sm font-bold text-text">Busy {when}</h2>
          <p className="m-0 mb-2 px-3 text-xs text-muted">Pick a repo to search only inside it.</p>
          <ul className="m-0 flex list-none flex-col p-0">{repos.map(([r, n]) => (
            <li key={r}><button type="button" onClick={() => scopeRepo(r)} className={row}>
              <span className="size-2 flex-none rounded-full" style={{ background: repoColor(r) }} />
              <span className="min-w-0 flex-1 truncate">{r}</span>
              <span className="font-mono text-xs text-faint tabular-nums">{n} session{n === 1 ? "" : "s"}</span>
            </button></li>))}</ul>
        </section>}
        <section aria-labelledby="s-else">
          <h2 id="s-else" className="m-0 mb-2 px-3 text-sm font-bold text-text">Not in the talk?</h2>
          <ul className="m-0 flex list-none flex-col p-0">
            <li><button type="button" onClick={() => layer("memory")} className={row}><span className="min-w-0 flex-1">Memory notes</span><span className="text-xs text-faint">rules, decisions, references</span></button></li>
            <li><button type="button" onClick={() => layer("git")} className={row}><span className="min-w-0 flex-1">Git commits</span><span className="text-xs text-faint">every repo, back to 2025-03</span></button></li>
          </ul>
          <p className="m-0 mt-4 px-3 text-xs text-faint"><Kbd>/</Kbd> type here · <Kbd>⌘K</Kbd> from anywhere · <Kbd>j</Kbd> <Kbd>k</Kbd> move through hits</p>
        </section>
      </div>
    </div>
  );
}

export function SearchView({ st, setSt, machine, setMachine, machines, recent, top, sessions, focusKey }: {
  st: SearchState; setSt: (s: SearchState) => void; machine: string; setMachine: (m: string) => void; machines: string[];
  recent: string[]; top: { query: string; n: number }[]; sessions: PaletteSession[]; focusKey: number;
}) {
  const [draft, setDraft] = useState(st);
  const [res, setRes] = useState<SearchResult | null>(null);
  const [ms, setMs] = useState(0);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [active, setActive] = useState(-1);
  const [unfold, setUnfold] = useState<Set<string>>(new Set());
  const [drawer, setDrawer] = useState(false);
  const [show, setShow] = useState<{ link: string; r: ShowResult | null; err?: string } | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const runId = useRef(0), showId = useRef(0);   // stale-request guards (ARRA Oracle v3 SimpleSearch): a late answer never overwrites a newer one
  const wide = () => window.matchMedia("(min-width: 1536px)").matches;

  useEffect(() => { input.current?.focus(); }, [focusKey]);
  useEffect(() => { setDraft(st); if (st.q) run(st); else setRes(null); }, [st.q, st.horizon, st.with, st.repo, st.role, st.session]);   // eslint-disable-line

  async function run(s: SearchState) {
    const id = ++runId.current;
    const p = new URLSearchParams({ q: s.q, limit: "40" });
    for (const k of ["horizon", "with", "repo", "role", "session"] as const) if (s[k]) p.set(k, s[k]);
    setBusy(true); setErr(null);
    const t = performance.now();
    try {
      const r = await get<SearchResult>("/api/search?" + p);
      if (id !== runId.current) return;
      setRes(r); setUnfold(new Set()); setActive(r.hits.length ? 0 : -1);
      if (document.activeElement === input.current && r.hits.length) input.current?.blur();   // j/k move at once (Panel A)
    } catch (e) { if (id === runId.current) setErr(String((e as Error).message)); }
    finally { if (id === runId.current) { setMs(Math.round(performance.now() - t)); setBusy(false); } }
  }

  const hits = useMemo(() => (res?.hits ?? []).filter(h => !machine || h.machines.includes(machine)), [res, machine]);
  const rows = useMemo(() => (st.session ? hits.map((h, i) => ({ h, i, more: [] as Hit[] })) : fold(hits)).flatMap(r => unfold.has(r.h.uid) ? [r, ...r.more.map((h, j) => ({ h, i: r.i + j + 1, more: [] as Hit[] }))] : [r]), [hits, unfold, st.session]);
  const selected = active >= 0 ? rows[Math.min(active, rows.length - 1)]?.h : undefined;
  // every repo with a session, for the repo box; the ones with a session this week, for the suggestions
  const repoNames = useMemo(() => [...new Set(sessions.map(x => x.repo).filter(r => r && r !== "(no repo)"))].sort(), [sessions]);
  // the window the suggestions follow: Nat clicked "15 days" before typing and saw nothing change
  const days = ({ "": 7, "7d": 7, "15d": 15, "1m": 31, "3m": 92, archive: 3650 } as Record<string, number>)[draft.horizon] ?? 7;
  const busyRepos = useMemo(() => {
    const since = new Date(Date.now() - days * 864e5).toISOString(), m = new Map<string, number>();
    for (const x of sessions) if (x.ts >= since && x.repo && x.repo !== "(no repo)") m.set(x.repo, (m.get(x.repo) ?? 0) + 1);
    return [...m.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8);
  }, [sessions, days]);
  // the hub lists at most its newest 500 sessions; past that, say how far back the list really reaches
  const oldest = useMemo(() => sessions.reduce((m, x) => (x.ts && x.ts < m ? x.ts : m), new Date().toISOString()), [sessions]);
  const reach = new Date(Date.now() - days * 864e5).toISOString() < oldest;
  const busyWhen = reach ? `since ${bkk(oldest).slice(0, 5)} (the newest ${sessions.length} sessions)`
    : days === 7 ? "this week" : `in the last ${({ 15: "15 days", 31: "month", 92: "3 months" } as Record<number, string>)[days]}`;

  useEffect(() => {   // the reader follows the selection; the drawer opens only on a click when the reader pane is not on screen
    if (!selected) { setShow(null); return; }
    const id = ++showId.current;
    setShow({ link: selected.link, r: null });
    get<ShowResult>(`/api/show?id=${encodeURIComponent(selected.link)}&before=3&after=3`)
      .then(r => { if (id === showId.current) setShow({ link: selected.link, r }); })
      .catch(e => { if (id === showId.current) setShow({ link: selected.link, r: null, err: String((e as Error).message) }); });
  }, [selected?.link]);   // eslint-disable-line

  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (drawer || ["INPUT", "TEXTAREA", "SELECT"].includes((e.target as HTMLElement).tagName) || e.metaKey || e.ctrlKey) return;
      if (e.key === "j") setActive(a => Math.min(a + 1, rows.length - 1));
      if (e.key === "k") setActive(a => Math.max(a - 1, 0));
      if (e.key === "Enter" && rows[active] && !wide()) setDrawer(true);
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  });

  const go = (next: SearchState) => { setDraft(next); if (next.q.trim()) setSt({ ...next, q: next.q.trim() }); };
  const narrow = (p: Partial<SearchState>) => go({ ...draft, ...p });
  const title = (h?: Hit) => h ? <>{shortRepo(h.repo_key)} · {h.session_name || h.title || h.session_uuid.slice(0, 8)}</> : "";
  const searched = !!st.q || !!res;
  const counts = res ? Object.fromEntries(["", ...machines].map(m => [m, (res.hits ?? []).filter(h => !m || h.machines.includes(m)).length])) : undefined;

  // ONE scope row for every screen (prism: the filters lived twice, a rail on desktop and chips on a phone)
  const scope = (
    <div className="flex flex-col gap-3">
      <div role="tablist" aria-label="What to search" className="-mx-5 flex gap-1 overflow-x-auto border-b border-line px-5 [scrollbar-width:none] sm:mx-0 sm:px-0">
        {LAYERS.map(l => (
          <button key={l.value} type="button" role="tab" aria-selected={draft.with === l.value} title={l.note} onClick={() => narrow({ with: l.value })}
            className={cx("-mb-px min-h-11 flex-none border-b-2 px-3 text-sm font-semibold whitespace-nowrap transition-colors duration-[120ms]",
              draft.with === l.value ? "border-accent text-text" : "border-transparent text-muted hover:text-text")}>{l.label}</button>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
        <div className="-mx-5 overflow-x-auto px-5 [scrollbar-width:none] sm:mx-0 sm:px-0" title="auto starts at 7 days and widens until it finds enough">
          <Seg label="When" value={draft.horizon} onChange={v => narrow({ horizon: v })} options={HORIZONS} />
        </div>
        {draft.with !== "memory" && draft.with !== "git" && <WhoPick role={draft.role} onChange={role => narrow({ role })} />}
        {machines.length > 1 && <Seg label="Machine" value={machine} onChange={setMachine} options={["", ...machines].map(m => ({ value: m, label: `${m || "all machines"}${counts ? ` · ${counts[m] ?? 0}` : ""}` }))} />}
        <label className="flex min-w-0 items-center gap-2 max-sm:w-full">
          <span className="text-xs font-semibold text-muted">in</span>
          <input aria-label="Only this repo" list="search-repos" className={inputCls + " h-9 min-h-9 w-full font-mono text-xs sm:w-56"} placeholder="any repo" value={draft.repo}
            onChange={e => { const v = e.target.value; setDraft({ ...draft, repo: v }); if (repoNames.includes(v)) go({ ...draft, repo: v }); }}
            onBlur={() => draft.repo !== st.repo && go(draft)} onKeyDown={e => e.key === "Enter" && go(draft)} />
          <datalist id="search-repos">{repoNames.map(r => <option key={r} value={r} />)}</datalist>
          {draft.repo && <button type="button" onClick={() => narrow({ repo: "" })} aria-label="Any repo" className="grid size-11 flex-none place-items-center rounded-lg text-muted hover:bg-raised hover:text-text"><Close size={16} /></button>}
        </label>
      </div>
    </div>
  );

  const reader = (
    <div className="flex h-full min-h-0 flex-col">
      {selected ? <>
        <div className="flex items-start gap-3 border-b border-line px-5 py-4">
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-bold text-text">{title(selected)}</div>
            <div className="mt-0.5 truncate font-mono text-xs text-faint">{selected.link}</div>
          </div>
          <Btn type="button" onClick={() => navigator.clipboard.writeText(selected.link)}>Copy link</Btn>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          {show?.err ? <State error>{show.err}</State> : show?.r ? <Context r={show.r} q={st.q} /> : <div className="p-5"><Loading label="Reading the message" /></div>}
        </div>
      </> : <p className="m-0 p-6 text-sm text-muted">No hit to read. Widen the window or drop a word.</p>}
    </div>
  );

  return (
    <>
      <header className="mb-5">
        <h1 className="m-0 text-xl font-extrabold tracking-[-0.02em] text-text">Search</h1>
        <p className="m-0 mt-1.5 text-sm text-muted">Every session on {machines.length ? machines.join(", ") : "every machine"}, each message counted once. Thai works inside words.</p>
      </header>
      <form onSubmit={e => { e.preventDefault(); go(draft); }} className="mb-4 flex gap-3">
        <label className="relative flex min-w-0 flex-1 items-center">
          <span className="pointer-events-none absolute left-4 text-muted"><Search size={20} /></span>
          <input id="q" ref={input} type="search" spellCheck={false} autoComplete="off" aria-label="Search every machine"
            placeholder={draft.with === "memory" ? "a rule, a decision, a reference…" : draft.with === "git" ? "a commit message, a repo…" : "Words from any session. Every word must appear."}
            value={draft.q} onChange={e => setDraft({ ...draft, q: e.target.value })}
            onKeyDown={e => { if (e.key === "ArrowDown" && rows.length) { e.preventDefault(); input.current?.blur(); setActive(0); } if (e.key === "Escape") input.current?.blur(); }}
            className="h-14 w-full rounded-xl border border-line bg-panel pr-4 pl-12 text-base text-text placeholder:text-faint hover:border-line-strong focus:border-accent" />
        </label>
        <Btn primary size="lg" type="submit">Search</Btn>
      </form>
      <div className="mb-8">{scope}
        {!draft.q.trim() && <p className="m-0 mt-3 text-xs text-muted">Type words to search. The choices above apply to the next search; {draft.horizon ? "the window is set" : "auto starts at 7 days and widens until it finds enough"}.</p>}
      </div>

      {!searched ? <Launch recent={recent} top={top} repos={busyRepos} when={busyWhen} pick={q => go({ ...draft, q })}
        scopeRepo={r => { setDraft({ ...draft, repo: r }); input.current?.focus(); }}
        layer={w => { setDraft({ ...draft, with: w }); input.current?.focus(); }} /> : (
      <div className="grid gap-8 lg:grid-cols-[248px_minmax(0,1fr)] 2xl:grid-cols-[248px_minmax(0,1fr)_minmax(380px,0.8fr)]">
        <aside aria-label="Where the hits come from" className="min-w-0">
          {res && <details className="rounded-2xl border border-line bg-panel lg:hidden">
            <summary className="flex min-h-12 cursor-pointer list-none items-center gap-2.5 px-5 text-sm font-semibold text-soft"><Filter size={16} />Sessions and repos in these hits</summary>
            <div className="flex flex-col gap-5 border-t border-line p-5"><Related hits={hits} st={draft} narrow={narrow} /></div>
          </details>}
          <div className="hidden flex-col gap-5 lg:flex">
            {res && <Related hits={hits} st={draft} narrow={narrow} />}
            {st.q && <AsCall st={st} />}
          </div>
        </aside>

        <section aria-label="Results" className="min-w-0">
          {busy && <div className="mb-3"><Loading label="Searching" /></div>}
          {draft.session && (
            <div className="mb-4 flex flex-wrap gap-2">
              <button type="button" onClick={() => narrow({ session: "" })} className="flex min-h-11 items-center gap-1.5 rounded-lg bg-accent-wash px-3 text-xs font-semibold text-accent">session {draft.session}<Close size={14} /></button>
            </div>
          )}
          {res && (
            <p role="status" aria-live="polite" className="m-0 mb-3 flex flex-wrap items-baseline gap-x-3 gap-y-1 px-5 text-sm text-muted">
              <b className="text-base text-text tabular-nums">{hits.length === 40 ? "Top 40" : machine && res.hits.length ? `${hits.length} of ${res.hits.length}` : `${hits.length} hits`}</b>
              <span>{machine ? `on ${machine}, ` : ""}{res.horizon === "archive" ? "from all time" : res.horizon === "window" ? "in the chosen window" : `from the last ${res.horizon}`}</span>
              {!!res.older_hits && res.horizon !== "archive" && <button type="button" onClick={() => narrow({ horizon: "archive" })} className={linkBtn}>show the {res.older_hits} older hits</button>}
              <span className="ml-auto font-mono text-xs text-faint">{res.searched_months.length} months · {ms} ms</span>
            </p>
          )}
          {err && <State error>{err}</State>}
          {res && !hits.length && (machine && res.hits.length
            ? <State>None of these {res.hits.length} hits are on {machine}. The machine choice narrows the hits already found; it does not search {machine} on its own.
                <span className="mt-3 block"><Btn type="button" onClick={() => setMachine("")}>Show all {res.hits.length}</Btn></span></State>
            : <State>No match. Pick a wider window above, or try fewer words: every word must appear.</State>)}
          <div className="flex flex-col gap-1">
            {rows.map((r, n) => <HitRow key={r.h.uid + n} h={r.h} q={st.q} active={n === active} more={unfold.has(r.h.uid) ? 0 : r.more.length}
              onMore={() => setUnfold(u => new Set(u).add(r.h.uid))}
              onOpen={() => { setActive(n); if (!wide()) setDrawer(true); }} />)}
          </div>
          {rows.length > 0 && <p className="mt-6 hidden px-5 text-xs text-faint lg:block"><Kbd>j</Kbd> <Kbd>k</Kbd> move · <Kbd>↵</Kbd> open · <Kbd>esc</Kbd> close · <Kbd>/</Kbd> search again</p>}
        </section>

        <aside aria-label="The selected hit" className="hidden 2xl:block">
          <div className="sticky top-4 h-[calc(100dvh-2rem)] overflow-hidden rounded-2xl border border-line bg-panel">{reader}</div>
        </aside>
      </div>)}

      <Drawer open={drawer} onClose={() => setDrawer(false)} title={title(selected)}
        note={selected?.link} onCopy={() => selected && navigator.clipboard.writeText(selected.link)}>
        {show?.err ? <State error>{show.err}</State> : show?.r ? <Context r={show.r} q={st.q} /> : <Loading label="Reading the message" />}
      </Drawer>
    </>
  );
}
