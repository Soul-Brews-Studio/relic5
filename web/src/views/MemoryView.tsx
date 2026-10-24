// Knowledge: the agents' memory notes as a feed, then one note as a page (Nat: "knowledge feed too", "memory page style
// that combo with code and repo and real file"). After the old ARRA Oracle Studio's Feed and DocDetail
// (ui-oracle apps/studio, 2026-04-19): a card per note with its kind and project; the note page renders the text, names
// the repo with a link to it, shows the real file it lives in and opens that file raw with line numbers; J/K step notes.
import { useEffect, useMemo, useState } from "react";
import { get, usePoll } from "../api";
import { ago, bkk, num, repoColor } from "../format";
import { Drawer } from "../components/Drawer";
import { Markdown, stripFrontmatter } from "../components/Markdown";
import { Search } from "../components/Icons";
import { Btn, inputCls, Kbd, Lbl, Loading, PageHead, State, Toggle } from "../components/ui";
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

export function MemoryView() {
  const p = usePoll<Listing>("/api/memory", 60000);
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const [project, setProject] = useState("");
  const [shown, setShown] = useState(PAGE);
  const [at, setAt] = useState<number | null>(null);

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
      <PageHead title="Knowledge" sub={<>{num(total)} one-fact notes agents keep per project: the rules Nat set, the decisions made, where things live. Pushed raw from every machine's <code className="font-mono text-sm text-soft">~/.claude/projects/*/memory</code>.</>} />
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
      <div className="mt-8"><Lbl>source</Lbl> <span className="font-mono text-xs text-faint">GET /api/memory · /api/show · /api/memory/file</span></div>
    </>
  );
}
