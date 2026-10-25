// Knowledge: the agents' memory notes as a feed, then one note as a page (Nat: "knowledge feed too", "memory page style
// that combo with code and repo and real file"). After the old ARRA Oracle Studio's Feed and DocDetail
// (ui-oracle apps/studio, 2026-04-19): a card per note with its kind and project; the note page renders the text, names
// the repo with a link to it, shows the real file it lives in and opens that file raw with line numbers; J/K step notes.
import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { get, usePoll } from "../api";
import { ago, bkk, num, repoColor } from "../format";
import { Drawer } from "../components/Drawer";
import { Markdown, stripFrontmatter } from "../components/Markdown";
import { Search } from "../components/Icons";
import { Btn, inputCls, Kbd, Lbl, Loading, PageHead, Seg, State, Toggle } from "../components/ui";

const Map3D = lazy(() => import("./Map3D"));
import type { ShowResult } from "../types";

interface Note { uid: string; link: string; ts: string; type: string; project: string; title: string; description: string; machines: string[]; home: string }
interface Listing { notes: Note[]; types: Record<string, number>; projects: Record<string, number> }

const KIND: Record<string, { word: string; color: string }> = {
  feedback: { word: "rule", color: "#64b5f6" }, project: { word: "decision", color: "#c792ea" },
  reference: { word: "reference", color: "#6fd6a0" }, user: { word: "about Nat", color: "#f5b73b" }, note: { word: "note", color: "#8a92a5" },
};
const kind = (t: string) => KIND[t] ?? KIND.note;
const PAGE = 60;

// "Soul-Brews-Studio-relic5" -> github.com/Soul-Brews-Studio/relic5. An org can hold hyphens, so the fleet's orgs are named.
const ORGS = ["Soul-Brews-Studio", "Soul-Brews-Hub", "laris-co", "nat-build-with-oracle", "Oracle-Landing", "StoneMeaw", "Stone-Meaw-Story",
  "Prakit-advertising", "the-oracle-keeps-the-human-human", "dryoungdo-wellness-clinic", "DustBoy-Chain", "DustBoyCNX", "Arkkra-Co", "nazt",
  "Arthur-Oracle-AI", "matchoproject", "ARRA-01", "Nonsense-Matters-Co", "Nonsense-Matters-Brewing", "PhoneBooth-project", "LarisLabs", "MaeOn-Lab", "MEYD-605"];
export function repoOf(project: string): { org: string; repo: string } | null {
  const p = project.replace(/-wt-.*$/, "");
  const org = ORGS.find(o => p.toLowerCase().startsWith(o.toLowerCase() + "-"));
  return org ? { org, repo: p.slice(org.length + 1) } : null;
}
/** Where the note lives on its machine: parts/<m>/memory/<home>/<project>/memory/<f> -> ~/.claude/projects/<project>/memory/<f>. */
function realFile(path: string | undefined, machines: string[]) {
  const m = /parts\/([^/]+)\/memory\/([^/]+)\/(.+)$/.exec(path ?? "");
  if (!m) return path ?? "";
  const home = m[2] === "claude" ? "~/.claude" : m[2].startsWith("nat-export-") ? "/Users/Shared/nat-export/.claude" : `~/.${m[2]}`;
  return `${machines[0] ?? m[1]}:${home}/projects/${m[3]}`;
}

function NoteCard({ n, q, onOpen }: { n: Note; q: string; onOpen: () => void }) {
  const k = kind(n.type), r = repoOf(n.project);
  return (
    <button type="button" onClick={onOpen} className="group block w-full rounded-2xl border border-line bg-panel px-5 py-4 text-left transition-colors hover:border-line-strong">
      <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
        <span className="rounded-full px-2.5 py-0.5 font-semibold" style={{ color: k.color, background: `color-mix(in srgb, ${k.color} 14%, transparent)` }}>{k.word}</span>
        <span className="flex items-center gap-1.5 font-semibold" style={{ color: repoColor(r?.repo ?? n.project) }}>
          <span className="size-2 rounded-full" style={{ background: repoColor(r?.repo ?? n.project) }} />{r ? r.repo : n.project}
        </span>
        <span className="text-muted" title={bkk(n.ts)}>{ago(n.ts)}</span>
        <span className="ml-auto text-faint">{n.machines.join(", ")}</span>
      </span>
      <span className="mt-2 block text-base font-semibold text-text group-hover:text-accent">{highlight(n.title.replace(/[-_]/g, " "), q)}</span>
      <span className="mt-1 line-clamp-2 block max-w-[78ch] text-sm leading-relaxed text-soft">{highlight(unq(n.description), q)}</span>
    </button>
  );
}
function highlight(text: string, q: string) {
  const words = q.split(/\s+/).filter(Boolean).map(w => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (!words.length) return text;
  return text.split(new RegExp(`(${words.join("|")})`, "gi")).map((p, i) => (i % 2 ? <mark key={i}>{p}</mark> : p));
}

/** One note as a page (the old Studio's DocDetail): header, the note itself, its repo and its real file. */
function NotePage({ n, onBack, onPrev, onNext }: { n: Note; onBack: () => void; onPrev?: () => void; onNext?: () => void }) {
  const [show, setShow] = useState<ShowResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [raw, setRaw] = useState<string | null>(null);
  useEffect(() => {
    setShow(null); setErr(null); setRaw(null);
    get<ShowResult>(`/api/show?id=${encodeURIComponent(n.link)}`).then(setShow).catch(e => setErr(String(e.message ?? e)));
  }, [n.link]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (["INPUT", "TEXTAREA"].includes((e.target as HTMLElement).tagName) || e.metaKey || e.ctrlKey) return;
      if (e.key === "j" && onNext) onNext();
      if (e.key === "k" && onPrev) onPrev();
      if (e.key === "u" || e.key === "Escape") onBack();
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  });
  const t = show?.target as (ShowResult["target"] & { path?: string; origin?: string }) | undefined;
  const k = kind(n.type), r = repoOf(n.project);
  const body = t?.text ? t.text.replace(/^[^\n]*:\s[^\n]*\n\n/, "") : "";
  const openRaw = async () => {
    if (!t?.path) return;
    const res = await fetch(`/api/memory/file?path=${encodeURIComponent(t.path)}`, { credentials: "same-origin" });
    setRaw(res.ok ? await res.text() : "this note's file is not on the hub");
  };
  return (
    <article className="rise max-w-[760px]">
      <button type="button" onClick={onBack} className="mb-6 -ml-2 inline-flex min-h-11 items-center rounded-lg px-2 text-sm text-muted hover:text-accent">← Back to Knowledge</button>
      <header className="mb-8 border-b border-line pb-6">
        <div className="mb-3 flex flex-wrap items-center gap-3 text-sm">
          <span className="rounded-full px-3 py-0.5 text-xs font-semibold" style={{ color: k.color, background: `color-mix(in srgb, ${k.color} 14%, transparent)` }}>{k.word}</span>
          <span className="text-muted">{bkk(n.ts)} Bangkok · {ago(n.ts)}</span>
        </div>
        <h1 className="m-0 text-xl leading-tight font-extrabold tracking-[-0.01em] text-text">{n.title.replace(/[-_]/g, " ")}</h1>
        <p className="m-0 mt-3 max-w-[70ch] text-base text-muted">{unq(n.description)}</p>
      </header>
      {err ? <State error>{err}</State> : !t ? <Loading label="Reading the note" /> : <Markdown text={stripFrontmatter(body)} />}
      <footer className="mt-12 flex flex-col gap-3 border-t border-line pt-6 text-sm">
        <div className="flex flex-wrap items-center gap-3">
          <span className="flex items-center gap-2 font-semibold" style={{ color: repoColor(r?.repo ?? n.project) }}>
            <span className="size-2 rounded-full" style={{ background: repoColor(r?.repo ?? n.project) }} />{r ? `${r.org}/${r.repo}` : n.project}
          </span>
          {r && <a href={`https://github.com/${r.org}/${r.repo}`} target="_blank" rel="noreferrer" className="inline-flex min-h-9 items-center rounded-lg bg-accent-wash px-3 text-xs font-semibold text-accent">View the repo on GitHub ↗</a>}
          {t?.origin && <a href={`#tab=search&q=${encodeURIComponent(n.title.replace(/[-_]/g, " "))}&session=${t.origin.slice(0, 8)}`} className="inline-flex min-h-9 items-center rounded-lg border border-line px-3 text-xs font-semibold text-soft hover:text-text">The session that wrote it · {t.origin.slice(0, 8)}</a>}
        </div>
        <button type="button" onClick={openRaw} disabled={!t?.path} className="inline-flex min-h-11 w-fit items-center rounded-lg font-mono text-xs text-muted hover:text-accent hover:underline">
          {realFile(t?.path, n.machines)}
        </button>
        <p className="m-0 text-xs text-faint">held by {n.machines.join(", ")} · one file per note, pushed raw by each machine (relic5 memory.py)</p>
      </footer>
      <nav className="mt-10 flex items-center justify-between gap-4 border-t border-line py-5">
        <Btn type="button" onClick={onPrev} disabled={!onPrev}><Kbd>K</Kbd> Previous</Btn>
        <span className="text-xs text-faint">J / K step · U back</span>
        <Btn type="button" onClick={onNext} disabled={!onNext}>Next <Kbd>J</Kbd></Btn>
      </nav>
      <Drawer open={raw != null} onClose={() => setRaw(null)} title={realFile(t?.path, n.machines)} note="the file as it is on disk, frontmatter included">
        <pre className="m-0 px-2 py-4 font-mono text-xs leading-relaxed text-soft">
          {(raw ?? "").split("\n").map((line, i) => (
            <div key={i} className="flex"><span className="mr-4 w-10 flex-none border-r border-line pr-3 text-right text-faint select-none">{i + 1}</span><span className="min-w-0 flex-1 whitespace-pre-wrap break-words">{line || " "}</span></div>
          ))}
        </pre>
      </Drawer>
    </article>
  );
}

const unq = (t: string) => t.replace(/\\"/g, '"');

/** The numbers behind the notes (Nat: "should be really stat"): by kind, by project, by month, by machine. */
function Stats({ notes, types, pick }: { notes: Note[]; types: Record<string, number>; pick: (p: Partial<{ type: string; project: string }>) => void }) {
  const total = notes.length;
  const byProject = new Map<string, number>(), byMonth = new Map<string, number>(), byMachine = new Map<string, number>();
  for (const n of notes) {
    byProject.set(n.project, (byProject.get(n.project) ?? 0) + 1);
    if (n.ts) byMonth.set(n.ts.slice(0, 7), (byMonth.get(n.ts.slice(0, 7)) ?? 0) + 1);
    for (const m of n.machines) byMachine.set(m, (byMachine.get(m) ?? 0) + 1);
  }
  const months = [...byMonth.entries()].sort(), mmax = Math.max(1, ...months.map(m => m[1]));
  const projects = [...byProject.entries()].sort((a, b) => b[1] - a[1]), pmax = projects[0]?.[1] ?? 1;
  const week = notes.filter(n => n.ts && Date.now() - +new Date(n.ts) < 7 * 864e5).length;
  const Bar = ({ label, n, max, color, onClick }: { label: string; n: number; max: number; color: string; onClick?: () => void }) => (
    <button type="button" onClick={onClick} className="block w-full rounded-lg px-2 py-1.5 text-left hover:bg-raised">
      <span className="flex justify-between gap-3 text-sm"><span className="min-w-0 truncate text-soft">{label}</span><span className="font-mono text-xs text-muted tabular-nums">{num(n)}</span></span>
      <span className="mt-1 block h-1.5 rounded-full bg-raised"><span className="block h-1.5 rounded-full" style={{ width: `${Math.max(2, (100 * n) / max)}%`, background: color }} /></span>
    </button>
  );
  return (
    <div className="rise flex flex-col gap-6">
      <div className="grid grid-cols-2 gap-6 md:grid-cols-4">
        {([["notes", total], ["projects", byProject.size], ["new this week", week], ["machines", byMachine.size]] as const).map(([l, n]) => (
          <div key={l}><div className="text-xs font-bold tracking-[0.14em] text-muted uppercase">{l}</div><div className="mt-1 text-2xl font-extrabold text-text tabular-nums">{num(n)}</div></div>))}
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-2xl border border-line bg-panel p-5">
          <h2 className="m-0 mb-3 text-base font-bold text-text">By kind</h2>
          {Object.entries(types).sort((a, b) => b[1] - a[1]).map(([t, n]) => <Bar key={t} label={`${t === "user" ? "about Nat" : kind(t).word + "s"} · ${t}`} n={n} max={total} color={kind(t).color} onClick={() => pick({ type: t })} />)}
          <p className="m-0 mt-3 text-xs text-muted">Claude Code's four kinds: <b>feedback</b> (a rule: how to work), <b>project</b> (a decision or fact about the work), <b>reference</b> (where something lives), <b>user</b> (who the human is).</p>
        </section>
        <section className="rounded-2xl border border-line bg-panel p-5">
          <h2 className="m-0 mb-3 text-base font-bold text-text">Written per month</h2>
          <div className="flex h-40 items-end gap-1.5" role="img" aria-label="Notes written per month">
            {months.map(([m, n]) => <div key={m} className="flex min-w-0 flex-1 flex-col items-center gap-1" title={`${m}: ${n} notes`}>
              <span className="font-mono text-[11px] text-muted">{n}</span>
              <span className="w-full rounded-t-[4px] bg-[#4a98d8]" style={{ height: `${Math.max(2, (100 * n) / mmax)}%` }} />
              <span className="font-mono text-[11px] text-faint">{m.slice(2)}</span></div>)}
          </div>
          <div className="mt-4 flex flex-wrap gap-x-5 gap-y-1 text-sm text-muted">{[...byMachine.entries()].map(([m, n]) => <span key={m}><b className="text-soft">{m}</b> holds {num(n)}</span>)}</div>
        </section>
      </div>
      <section className="rounded-2xl border border-line bg-panel p-5">
        <h2 className="m-0 mb-3 text-base font-bold text-text">Projects with the most notes</h2>
        <div className="grid gap-x-8 md:grid-cols-2">{projects.slice(0, 20).map(([pr, n]) => <Bar key={pr} label={repoOf(pr)?.repo ?? pr} n={n} max={pmax} color={repoColor(repoOf(pr)?.repo ?? pr)} onClick={() => pick({ project: pr })} />)}</div>
      </section>
      <section className="rounded-2xl border border-line bg-panel p-5">
        <h2 className="m-0 text-base font-bold text-text">What is in Claude Code memory</h2>
        <div className="mt-2 max-w-[80ch]"><Markdown compact text={"Every project an agent works in gets a folder `~/.claude/projects/<project>/memory/`. Each note is one `.md` file holding one fact, with frontmatter: `name`, `description` (the line shown here) and `type` (one of the four kinds). `MEMORY.md` in the same folder is the index Claude Code loads at the start of every session, one line per note; the notes themselves are read when they matter. relic5-push sends every machine's folders raw; `relic5 index` folds a note copied to two machines into one, and keeps an edited copy as a second version."} /></div>
      </section>
    </div>
  );
}

interface MemPoint { uid: string; x: number; y: number; z: number; type: string; project: string; title: string; ts: string; machines: string[] }

/** Every note as a point placed by its own vector (GET /api/memory/map); colour is the kind. */
function NotesMap({ notes, onOpen }: { notes: Note[]; onOpen: (uid: string) => void }) {
  const p = usePoll<{ notes: number; embedded: number; explained: number[]; points: MemPoint[] }>("/api/memory/map", 0);
  const [hover, setHover] = useState<{ i: number; x: number; y: number }>({ i: -1, x: 0, y: 0 });
  const [sel, setSel] = useState(-1);
  const pts = p.data?.points ?? [];
  const colors = useMemo(() => pts.map(x => kind(x.type).color), [pts]);
  const dim = useMemo(() => pts.map(() => false), [pts]);
  if (p.error && !p.data) return <State error>{p.error}</State>;
  if (!p.data) return <Loading label="Placing the notes" />;
  if (!pts.length) return <State>{`None of the ${num(p.data.notes)} notes has a vector of its own yet. The embed worker now takes memory notes too (GET /api/missing lists them); after its next run they show here, each placed by its own meaning.`}</State>;
  const hv = hover.i >= 0 ? pts[hover.i] : undefined;
  const known = new Set(notes.map(n => n.uid));
  return (
    <div className="rise">
      <p className="m-0 mb-3 text-sm text-muted">{num(p.data.embedded)} of {num(p.data.notes)} notes have their own vector · close points say similar things · colour is the kind · click a point to open its note</p>
      <div className="relative h-[min(70vh,780px)] min-h-[420px] overflow-hidden rounded-2xl border border-line bg-[radial-gradient(ellipse_at_center,var(--raised)_0%,var(--deep)_75%)]">
        <Suspense fallback={<div className="p-6"><Loading label="Loading the 3D view" /></div>}>
          <Map3D points={pts.map(x => ({ sid: x.uid, x: x.x, y: x.y, z: x.z, n: 1, ts: x.ts, repo: x.project, name: x.title, machines: x.machines }))} colors={colors} dim={dim}
            selected={sel} spin={sel < 0} onHover={(i, x, y) => setHover({ i, x, y })} onSelect={i => { setSel(i); if (known.has(pts[i].uid)) onOpen(pts[i].uid); }} />
        </Suspense>
        {hv && <div className="pointer-events-none absolute z-10 max-w-[340px] rounded-xl border border-line-strong bg-panel px-3.5 py-2.5 text-sm shadow-[var(--shadow-pop)]" style={{ left: hover.x + 14, top: hover.y + 14 }}>
          <div className="font-semibold text-text">{hv.title.replace(/[-_]/g, " ")}</div>
          <div className="mt-0.5 flex items-center gap-1.5 text-xs text-muted"><span className="size-2 rounded-full" style={{ background: colors[hover.i] }} />{kind(hv.type).word} · {repoOf(hv.project)?.repo ?? hv.project}</div>
        </div>}
        <p className="pointer-events-none absolute bottom-3 left-4 m-0 font-mono text-xs text-faint">pca-3d of each note's own vector · axes explain {p.data.explained.map(e => Math.round(e * 100) + "%").join(" / ")} · drag to turn · wheel to zoom</p>
      </div>
    </div>
  );
}

export function MemoryView() {
  const p = usePoll<Listing>("/api/memory", 60000);
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const [project, setProject] = useState("");
  const [shown, setShown] = useState(PAGE);
  const [at, setAt] = useState<number | null>(null);
  const [mode, setMode] = useState<"feed" | "stats" | "map">("feed");

  const list = useMemo(() => {
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    return (p.data?.notes ?? []).filter(n => (!type || n.type === type) && (!project || n.project === project) &&
      words.every(w => (n.title + " " + n.description + " " + n.project).toLowerCase().includes(w)));
  }, [p.data, q, type, project]);

  if (p.error && !p.data) return <State error>{p.error}</State>;
  if (!p.data) return <Loading label="Reading the notes" />;
  if (at != null && list[at]) {
    return <NotePage n={list[at]} onBack={() => setAt(null)}
      onPrev={at > 0 ? () => setAt(at - 1) : undefined} onNext={at < list.length - 1 ? () => setAt(at + 1) : undefined} />;
  }
  const total = p.data.notes.length;
  const projects = Object.entries(p.data.projects);
  return (
    <>
      <PageHead title="Knowledge" sub={<>{num(total)} one-fact notes agents keep per project: the rules Nat set, the decisions made, where things live. Pushed raw from every machine's <code className="font-mono text-sm text-soft">~/.claude/projects/*/memory</code>.</>}>
        <Seg label="View" value={mode} onChange={setMode} options={[{ value: "feed", label: "Feed" }, { value: "stats", label: "Stats" }, { value: "map", label: "Map" }]} />
      </PageHead>
      {mode === "stats" && <Stats notes={p.data.notes} types={p.data.types} pick={x => { if (x.type !== undefined) setType(x.type); if (x.project !== undefined) setProject(x.project); setMode("feed"); }} />}
      {mode === "map" && <NotesMap notes={list} onOpen={uid => { const i = list.findIndex(n => n.uid === uid); if (i >= 0) setAt(i); }} />}
      {mode === "feed" && <>
      <div className="mb-6 flex flex-col gap-4">
        <label className="relative flex items-center">
          <span className="pointer-events-none absolute left-4 text-muted"><Search size={20} /></span>
          <input type="search" value={q} onChange={e => { setQ(e.target.value); setShown(PAGE); }} placeholder="Filter by words in the title, description or project"
            aria-label="Filter the notes" spellCheck={false}
            className="h-14 w-full rounded-xl border border-line bg-panel pr-4 pl-12 text-base text-text placeholder:text-faint hover:border-line-strong focus:border-accent" />
        </label>
        <div className="flex flex-wrap items-center gap-2">
          <Toggle pressed={!type} onClick={() => setType("")}>everything <span className="font-mono text-xs text-faint">{num(total)}</span></Toggle>
          {Object.entries(p.data.types).sort((a, b) => b[1] - a[1]).map(([t, n]) => (
            <Toggle key={t} pressed={type === t} onClick={() => { setType(type === t ? "" : t); setShown(PAGE); }}>
              <span className="size-2 rounded-full" style={{ background: kind(t).color }} />{t === "user" ? "about Nat" : kind(t).word + "s"} <span className="font-mono text-xs text-faint">{num(n)}</span>
            </Toggle>
          ))}
          <select aria-label="Project" value={project} onChange={e => { setProject(e.target.value); setShown(PAGE); }} className={inputCls + " ml-auto w-full sm:w-72"}>
            <option value="">every project ({projects.length})</option>
            {projects.map(([pr, n]) => <option key={pr} value={pr}>{repoOf(pr)?.repo ?? pr} · {n}</option>)}
          </select>
        </div>
      </div>
      <p role="status" className="m-0 mb-3 flex items-baseline gap-3 text-sm text-muted">
        <b className="text-base text-text tabular-nums">{num(list.length)}</b>{q || type || project ? "notes match" : "notes"} · newest first
      </p>
      {list.length === 0 && <State>{total === 0
        ? "No memory notes on this hub yet. Each machine's push sends them; a copy restored from an older snapshot has none until its next refresh."
        : "No note matches. Clear the words or pick everything."}</State>}
      <div className="grid gap-3 xl:grid-cols-2">
        {list.slice(0, shown).map((n, i) => <NoteCard key={n.uid} n={n} q={q} onOpen={() => setAt(i)} />)}
      </div>
      {list.length > shown && <div className="mt-6"><Btn type="button" onClick={() => setShown(shown + PAGE * 2)}>Show {num(Math.min(PAGE * 2, list.length - shown))} more</Btn></div>}
      </>}
      <div className="mt-8"><Lbl>source</Lbl> <span className="font-mono text-xs text-faint">GET /api/memory · /api/memory/map · /api/show · /api/memory/file</span></div>
    </>
  );
}
