// Oracles (Nat, 2026-10-24: "1 page that each oracle bring to human / collect data and generate a prompt to create a
// character / style? and enlightenment"). The list is every oracle that owns a ψ vault (GET /api/oracles); one oracle
// opens as its own page (GET /api/oracle?name=): who it says it is, what it learned, how its sessions went, the rules
// its human set, its newest sessions, the words its notes use most, and two prompts built only from those notes, one
// for its character and style, one for what it has come to understand. Copy a prompt into Claude; nothing is sent.
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { get, usePoll } from "../api";
import { ago, bkk, num, repoColor } from "../format";
import { Markdown } from "../components/Markdown";
import { Search } from "../components/Icons";
import { Btn, cx, Lbl, Loading, PageHead, Seg, State, Toggle } from "../components/ui";
import { Drawer } from "../components/Drawer";

const ModelView = lazy(() => import("./ModelView"));

export interface Artifact { id: string; oracle: string; title: string; kind: "image" | "video" | "model" | "web"; ext: string; mime: string; bytes: number; at: string; by?: string; note?: string; prompt?: string; url: string }

/** What an artifact looks like in a tile and in the big view: a picture, a video, a 3D model, or a web piece in a
 *  sandboxed frame (the hub also serves it under a CSP sandbox, so its scripts never touch the hub). */
function Show({ a, big }: { a: Artifact; big?: boolean }) {
  if (a.kind === "image") return <img src={a.url} alt={a.title} loading="lazy" className={cx("h-full w-full", big ? "object-contain" : "object-cover")} />;
  if (a.kind === "video") return <video src={a.url} controls={big} muted={!big} loop autoPlay={!big} playsInline className={cx("h-full w-full", big ? "object-contain" : "object-cover")} />;
  // a web piece runs only when opened: as a live tile its labels collided at card size (relic4-scan's review)
  if (a.kind === "web") return big ? <iframe src={a.url} title={a.title} sandbox="allow-scripts" className="h-full w-full border-0 bg-white" />
    : <div className="grid h-full w-full place-items-center bg-[radial-gradient(circle_at_50%_45%,var(--accent-wash),var(--deep)_70%)] text-center">
        <span><span className="mx-auto mb-2 grid size-12 place-items-center rounded-full bg-accent text-xl font-bold text-on-accent">▶</span>
          <span className="block font-mono text-xs text-muted">web piece · open to run</span></span></div>;
  return big ? <Suspense fallback={<Loading label="Loading the 3D model" />}><ModelView url={a.url} label={a.title} /></Suspense>
    : <div className="grid h-full w-full place-items-center bg-deep font-mono text-sm text-muted">3D model · .{a.ext}</div>;
}

/** A prompt as text in the page's own scroll (relic4-scan's review: never a scrollbar inside a card): wrapped at 80
 *  characters, folded to 12 visible lines (by height: a note is one long line that wraps), then "Show all". */
function PromptText({ text }: { text: string }) {
  const [all, setAll] = useState(false);
  const [long, setLong] = useState(false);
  const ref = useRef<HTMLPreElement>(null);
  useEffect(() => { const el = ref.current; if (el) setLong(el.scrollHeight > el.clientHeight + 4 || all); }, [text, all]);
  return (
    <div className="mt-4 rounded-xl border border-line bg-deep p-4">
      <div className="relative">
        <pre ref={ref} className={cx("m-0 max-w-[80ch] overflow-hidden font-mono text-xs leading-[1.65] whitespace-pre-wrap break-words text-soft", !all && "max-h-[calc(12*1.65*0.75rem)]")}>{text}</pre>
        {!all && long && <div aria-hidden className="pointer-events-none absolute inset-x-0 bottom-0 h-10 bg-gradient-to-t from-[var(--deep)] to-transparent" />}
      </div>
      {long && <button type="button" onClick={() => setAll(!all)} className="mt-2 inline-flex min-h-9 items-center text-xs font-semibold text-accent">
        {all ? "Show less" : `Show all ${text.split("\n").length} lines`}</button>}
    </div>
  );
}

/** The oracle's artifacts as a gallery; a tile opens the piece big with its record (who sent it, when, the prompt). */
export function Gallery({ items, empty }: { items: Artifact[]; empty?: string }) {
  const [open, setOpen] = useState<Artifact | null>(null);
  if (!items.length) return empty ? <p className="m-0 text-sm text-muted">{empty}</p> : null;
  return <>
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-5">
      {items.map(a => (
        <button key={a.id} type="button" onClick={() => setOpen(a)} className="group overflow-hidden rounded-xl border border-line bg-panel text-left hover:border-line-strong">
          <div className="aspect-square overflow-hidden bg-deep"><Show a={a} /></div>
          <div className="px-3 py-2"><div className="line-clamp-2 text-sm font-semibold break-words text-text group-hover:text-accent" title={a.title}>{a.title}</div>
            <div className="mt-0.5 line-clamp-2 text-xs break-words text-muted">{a.kind} · {a.oracle} · {ago(a.at)}</div></div>
        </button>
      ))}
    </div>
    <Drawer open={!!open} onClose={() => setOpen(null)} title={open?.title ?? ""} note={open ? `${open.kind} · .${open.ext} · ${num(open.bytes)} bytes · sha256 ${open.id}… · ${bkk(open.at)} · by ${open.by ?? "unknown"}` : ""}
      onCopy={open ? () => navigator.clipboard.writeText(location.origin + open.url) : undefined}>
      {open && <div className="grid h-full grid-rows-[minmax(0,1fr)_auto]">
        <div className="min-h-[50vh] bg-deep"><Show a={open} big /></div>
        {(open.prompt || open.note) && <div className="border-t border-line px-6 py-4 text-sm">
          {open.note && <p className="m-0 mb-2 text-soft">{open.note}</p>}
          {open.prompt && <><Lbl>the prompt that made it</Lbl><pre className="m-0 mt-2 max-h-40 overflow-auto font-mono text-xs whitespace-pre-wrap text-muted">{open.prompt}</pre></>}
        </div>}
      </div>}
    </Drawer>
  </>;
}

interface Oracle { name: string; path: string; notes: number; sections: Record<string, number>; newest?: number; machines: string[]; soul: number; learnings: number; retros: number }
interface NoteLite { title: string; path: string; ts: string; text: string }
interface Portrait {
  name: string; path: string; machines: string[]; notes: number; sections: Record<string, number>; newest?: number; repo: string;
  soul: NoteLite[]; learnings: NoteLite[]; retros: NoteLite[]; rules: { title: string; description: string; link: string }[];
  sessions: { sid: string; name?: string; ts?: string }[]; words: [string, number][]; prompts: { character: string; enlighten: string; pet?: string }; error?: string;
}

const when = (ms?: number) => (ms ? new Date(ms).toISOString() : undefined);

function Copy({ text, label, short }: { text: string; label: string; short?: string }) {
  const [done, setDone] = useState(false);
  return <Btn primary type="button" aria-label={label} onClick={() => { navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1800); }}>
    {done ? "Copied" : short ? <><span className="sm:hidden">{short}</span><span className="max-sm:hidden">{label}</span></> : label}</Btn>;
}

function Notes({ title, sub, notes, empty }: { title: string; sub: string; notes: NoteLite[]; empty: string }) {
  return (
    <section className="rounded-2xl border border-line bg-panel p-5">
      <h2 className="m-0 text-base font-bold text-text">{title}</h2>
      <p className="m-0 mt-1 mb-4 text-sm text-muted">{sub}</p>
      {notes.length ? <ul className="m-0 flex list-none flex-col gap-4 p-0">{notes.map(n => (
        <li key={n.path} className="border-t border-line pt-4 first:border-t-0 first:pt-0">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1"><b className="text-sm text-text">{n.title.replace(/^\d{4}-\d{2}-\d{2}[_-]?/, "").replace(/[-_]/g, " ")}</b><span className="text-xs text-muted" title={bkk(n.ts)}>{ago(n.ts)}</span></div>
          <div className="mt-1.5 max-w-[78ch]"><Markdown text={n.text} compact /></div>
          <div className="mt-1 truncate font-mono text-xs text-faint">ψ/{n.path}</div>
        </li>))}</ul> : <p className="m-0 text-sm text-muted">{empty}</p>}
    </section>
  );
}

function OraclePage({ name, onBack }: { name: string; onBack: () => void }) {
  const [p, setP] = useState<Portrait | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tab, setTab] = useState<"character" | "enlighten" | "pet">("character");
  const [arts, setArts] = useState<Artifact[]>([]);
  useEffect(() => {
    setP(null); setErr(null);
    get<Portrait>(`/api/oracle?name=${encodeURIComponent(name)}`).then(setP).catch(e => setErr(String(e.message ?? e)));
    get<{ artifacts: Artifact[] }>(`/api/artifacts?oracle=${encodeURIComponent(name)}`).then(r => setArts(r.artifacts)).catch(() => setArts([]));
  }, [name]);
  if (err) return <State error>{err}</State>;
  if (!p) return <Loading label={`Gathering ${name}'s notes`} />;
  const max = Math.max(1, ...p.words.map(w => w[1]));
  const sections = Object.entries(p.sections).sort((a, b) => b[1] - a[1]).slice(0, 10);
  const top = sections[0]?.[1] ?? 1;
  return (
    <article className="rise">
      <button type="button" onClick={onBack} className="mb-6 -ml-2 inline-flex min-h-11 items-center rounded-lg px-2 text-sm text-muted hover:text-accent">← All oracles</button>
      <header className="mb-8 flex flex-wrap items-end gap-6">
        <div className="min-w-0 flex-1">
          <h1 className="m-0 text-2xl leading-tight font-extrabold tracking-[-0.02em]" style={{ color: repoColor(p.name) }}>{p.name}</h1>
          <p className="m-0 mt-2 text-base text-muted">{num(p.notes)} notes in its ψ vault · newest {ago(when(p.newest))} · on {p.machines.join(", ")}</p>
          <p className="m-0 mt-1 truncate font-mono text-xs text-faint">{p.path}</p>
        </div>
      </header>

      <section className="mb-6 rounded-2xl border border-accent/40 bg-panel p-5">
        <div className="flex items-center gap-3">
          <div role="tablist" aria-label="Prompt" className="flex min-w-0 flex-1 gap-1 overflow-x-auto [scrollbar-width:none]">
            {([["character", "Character"], ["enlighten", "Enlighten"], ["pet", "Pet"]] as const).filter(([k]) => k !== "pet" || p.prompts.pet).map(([k, l]) => (
              <button key={k} type="button" role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
                className={cx("-mb-px min-h-11 flex-none border-b-2 px-2.5 text-sm font-semibold whitespace-nowrap sm:px-3", tab === k ? "border-accent text-text" : "border-transparent text-muted hover:text-text")}>{l}</button>
            ))}
          </div>
          <span className="flex-none"><Copy text={p.prompts[tab] ?? ""} label="Copy the prompt" short="Copy" /></span>
        </div>
        <p className="m-0 mt-3 text-sm text-muted">{tab === "pet"
          ? `For Pet Studio (pet-studio/ in relic5, on the Mac that holds the pets): give it to studio_auto_sprite to draw ${p.name}'s desk pet and its seven moods, then keep the GIFs here with relic_artifact_put.`
          : tab === "character"
          ? `Built only from ${p.name}'s soul notes, learnings and the rules set for it. Paste it into Claude to get its character, voice and style, each claim quoted from a note.`
          : `Built from ${p.name}'s newest learnings and retrospectives. Paste it into Claude to hear what ${p.name} has come to understand, and where the notes are thin.`}</p>
        <PromptText text={p.prompts[tab] ?? ""} />
      </section>

      <section className="mb-6 rounded-2xl border border-line bg-panel p-5">
        <div className="mb-3 flex flex-wrap items-baseline gap-3"><h2 className="m-0 text-base font-bold text-text">Made for {p.name}</h2><span className="text-sm text-muted">{arts.length ? `${arts.length} artifacts` : ""}</span></div>
        <Gallery items={arts} empty={`Nothing yet. An agent can add an image, a video, a 3D model or a web piece with the MCP tool relic_artifact_put {"oracle": "${p.name}", "filename": "portrait.png", "data": "<base64>", "prompt": "…"}; paste the character prompt above to an image model first.`} />
      </section>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="flex min-w-0 flex-col gap-6">
          <Notes title="Who it says it is" sub="Its soul notes (memory/resonance), newest first." notes={p.soul} empty={`${p.name} has no soul notes on the hub. Its character prompt leans on its learnings and rules.`} />
          <Notes title="What it learned" sub="memory/learnings, newest first." notes={p.learnings} empty="No learnings on the hub yet." />
          <Notes title="How its sessions went" sub="memory/retrospectives, newest first." notes={p.retros} empty="No retrospectives on the hub yet." />
        </div>
        <aside className="flex min-w-0 flex-col gap-6">
          {p.words.length > 0 && <section className="rounded-2xl border border-line bg-panel p-5">
            <Lbl>the words its notes use</Lbl>
            <div className="mt-3 flex flex-wrap items-baseline gap-x-3 gap-y-1.5">
              {p.words.map(([w, n]) => { const r = Math.log1p(n) / Math.log1p(max); return <span key={w} title={`${n} notes`}
                style={{ fontSize: `${12 + Math.round(10 * r)}px`, color: `color-mix(in srgb, ${repoColor(w)} ${Math.round(50 + 50 * r)}%, var(--muted))` }}
                className={n / max > 0.5 ? "font-bold" : n / max > 0.25 ? "font-semibold" : ""}>{w}</span>; })}
            </div>
          </section>}
          <section className="rounded-2xl border border-line bg-panel p-5">
            <Lbl>where its notes are</Lbl>
            <ul className="m-0 mt-3 flex list-none flex-col gap-2 p-0">{sections.map(([s, n]) => (
              <li key={s}><div className="flex justify-between gap-3 text-sm"><span className="min-w-0 truncate text-soft">{s}</span><span className="font-mono text-xs text-muted">{num(n)}</span></div>
                <div className="mt-1 h-1.5 rounded-full bg-raised"><div className="h-1.5 rounded-full bg-accent" style={{ width: `${Math.max(2, (100 * n) / top)}%` }} /></div></li>))}</ul>
          </section>
          <section className="rounded-2xl border border-line bg-panel p-5">
            <Lbl>rules its human set</Lbl>
            {p.rules.length ? <ul className="m-0 mt-3 flex list-none flex-col gap-3 p-0">{p.rules.map(r => (
              <li key={r.link}><b className="block text-sm text-text">{r.title.replace(/[-_]/g, " ")}</b><span className="text-sm text-muted">{r.description}</span></li>))}</ul>
              : <p className="m-0 mt-3 text-sm text-muted">No Claude Code memory notes for this oracle's repo.</p>}
          </section>
          <section className="rounded-2xl border border-line bg-panel p-5">
            <Lbl>newest sessions</Lbl>
            {p.sessions.length ? <ul className="m-0 mt-3 flex list-none flex-col gap-2 p-0">{p.sessions.map(s => (
              <li key={s.sid}><a href={`#tab=search&session=${s.sid.slice(0, 8)}`} className="block text-sm text-soft no-underline hover:text-accent">{s.name || s.sid.slice(0, 8)}</a>
                <span className="text-xs text-muted">{ago(s.ts)}</span></li>))}</ul>
              : <p className="m-0 mt-3 text-sm text-muted">No sessions found under this name.</p>}
          </section>
        </aside>
      </div>
    </article>
  );
}

/** The lineage scan's record for a vault: matched by repo folder (".../neo-oracle/ψ" -> "neo-oracle"), then by name. */
interface LNodeLite { name: string; repo?: string; parent: string | null; awakened: boolean; date?: string; children: number }
function lineageIndex(nodes: LNodeLite[]) {
  const byRepo = new Map<string, LNodeLite>(), byName = new Map<string, LNodeLite>();
  for (const n of nodes) {
    if (n.repo) byRepo.set(n.repo.split("/").pop()!.toLowerCase(), n);
    byName.set(n.name.toLowerCase(), n);
  }
  return (o: Oracle) => {
    const dir = (o.path.replace(/\/ψ\/?$/, "").split("/").pop() ?? "").toLowerCase();
    return byRepo.get(dir) ?? byName.get(o.name.toLowerCase()) ?? byName.get(o.name.toLowerCase().replace(/-oracle$/, ""));
  };
}

type Sort = "size" | "recent" | "soul" | "name";
const SORTS: Record<Sort, (a: Oracle, b: Oracle) => number> = {
  size: (a, b) => b.notes - a.notes,
  recent: (a, b) => (b.newest ?? 0) - (a.newest ?? 0),
  soul: (a, b) => b.soul + b.learnings + b.retros - (a.soul + a.learnings + a.retros) || b.notes - a.notes,
  name: (a, b) => a.name.localeCompare(b.name),
};

/** notes on a log scale, so a 25k-note vault and a 40-note vault both read on one bar */
const logW = (n: number, max: number) => (n > 0 ? Math.max(3, (100 * Math.log10(n + 1)) / Math.log10(max + 1)) : 0);

export function OraclesView() {
  const p = usePoll<{ oracles: Oracle[]; vaults: number }>("/api/oracles", 300000);
  const art = usePoll<{ artifacts: Artifact[]; oracles: Record<string, number> }>("/api/artifacts?limit=12", 60000);
  const lin = usePoll<{ nodes: LNodeLite[] }>("/api/lineage", 0);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<string | null>(() => new URLSearchParams(location.hash.slice(1)).get("oracle"));
  const [only, setOnly] = useState(false);
  const [sort, setSort] = useState<Sort>("size");
  const [all, setAll] = useState(false);
  const fam = useMemo(() => lineageIndex(lin.data?.nodes ?? []), [lin.data]);
  const list = useMemo(() => {
    const w = q.toLowerCase().trim();
    return (p.data?.oracles ?? []).filter(o => (!w || o.name.toLowerCase().includes(w)) && (!only || o.soul + o.learnings + o.retros > 0)).sort(SORTS[sort]);
  }, [p.data, q, only, sort]);
  const go = (name: string | null) => {
    setOpen(name);
    history.replaceState(null, "", name ? `#tab=oracles&oracle=${encodeURIComponent(name)}` : "#tab=oracles");
    document.getElementById("main")?.scrollTo({ top: 0 });
  };
  if (open) return <OraclePage name={open} onBack={() => go(null)} />;
  if (p.error && !p.data) return <State error>{p.error}</State>;
  if (!p.data) return <Loading label="Reading the vaults" />;
  const os = p.data.oracles, max = Math.max(1, ...os.map(o => o.notes));
  const voiced = os.filter(o => o.soul + o.learnings + o.retros > 0).length;
  const week = os.filter(o => o.newest && Date.now() - o.newest < 7 * 864e5).length;
  const shown = all || q ? list : list.slice(0, 60);
  return (
    <>
      <PageHead title="Oracles" sub={<>Every oracle that keeps its own ψ vault on the hub. Open one to meet it: what it says it is, what it learned, and the prompts that bring out its character.</>} />
      <p className="m-0 mb-8 max-w-[60ch] text-lg leading-snug text-soft text-pretty">
        <b className="text-text tabular-nums">{num(os.length)}</b> vaults, <b className="text-text tabular-nums">{num(os.reduce((a, o) => a + o.notes, 0))}</b> notes.{" "}
        <b className="text-text tabular-nums">{num(voiced)}</b> have soul notes, learnings or retros of their own; <b className="text-text tabular-nums">{num(week)}</b> wrote something this week.
      </p>

      {(art.data?.artifacts.length ?? 0) > 0 && <section className="mb-10">
        <div className="mb-3 flex items-baseline gap-3"><h2 className="m-0 text-base font-bold text-text">Newest made for the oracles</h2><span className="text-sm text-muted">{art.data!.artifacts.length} of {num(Object.values(art.data!.oracles).reduce((a, b) => a + b, 0))}</span></div>
        <Strip items={art.data!.artifacts} onOracle={go} />
      </section>}

      <div className="sticky top-0 z-[3] -mx-1 mb-4 flex flex-wrap items-center gap-3 bg-bg/90 px-1 py-2 backdrop-blur-sm">
        <label className="relative flex w-full min-w-0 items-center sm:w-auto sm:flex-1 sm:max-w-sm">
          <span className="pointer-events-none absolute left-3.5 text-muted"><Search size={16} /></span>
          <input type="search" value={q} onChange={e => setQ(e.target.value)} placeholder="Find an oracle by name" aria-label="Find an oracle"
            className="h-11 w-full rounded-lg border border-line bg-panel pr-3 pl-10 text-sm text-text placeholder:text-faint hover:border-line-strong focus:border-accent" />
        </label>
        <Seg label="Sort" value={sort} onChange={setSort} options={[{ value: "size", label: "Biggest" }, { value: "recent", label: "Recent" }, { value: "soul", label: "Most self" }, { value: "name", label: "A–Z" }]} />
        <Toggle pressed={only} onClick={() => setOnly(!only)}>With a voice</Toggle>
        <span className="text-sm text-muted tabular-nums">{num(list.length)} shown</span>
      </div>

      <div role="list" className="overflow-hidden rounded-2xl border border-line bg-panel">
        <div aria-hidden className="hidden grid-cols-[minmax(0,1.6fr)_minmax(0,1.4fr)_repeat(3,4.5rem)_minmax(0,1fr)_5.5rem] gap-4 border-b border-line px-5 py-3 text-xs font-bold tracking-[0.14em] text-muted uppercase lg:grid">
          <span>oracle</span><span>notes</span><span className="text-right">soul</span><span className="text-right">learned</span><span className="text-right">retros</span><span>machines</span><span className="text-right">last</span>
        </div>
        {shown.map(o => {
          const f = fam(o), c = repoColor(o.name);
          return (
            <button key={o.name} role="listitem" type="button" onClick={() => go(o.name)}
              className="group grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-1.5 border-b border-line px-5 py-3 text-left transition-colors duration-[120ms] last:border-b-0 hover:bg-raised focus-visible:bg-raised lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1.4fr)_repeat(3,4.5rem)_minmax(0,1fr)_5.5rem]">
              <span className="flex min-w-0 items-center gap-2.5">
                <span className="size-2.5 flex-none rounded-full" style={f?.awakened ? { background: c } : { boxShadow: `inset 0 0 0 2px ${c}` }} title={f?.awakened ? "awakened" : undefined} />
                <span className="min-w-0">
                  <b className="block truncate text-[15px] text-text group-hover:text-accent">{o.name}</b>
                  {f && (f.parent || f.children > 0) && <span className="block truncate text-xs text-muted">{f.parent ? <>budded from <span className="text-soft">{f.parent}</span></> : null}{f.parent && f.children ? " · " : ""}{f.children ? `${f.children} budded from it` : ""}</span>}
                </span>
              </span>
              <span className="text-right text-xs text-muted lg:hidden">{ago(when(o.newest))}</span>
              <span className="col-span-2 flex items-center gap-3 lg:col-span-1">
                <span className="h-1.5 min-w-0 flex-1 rounded-full bg-raised"><span className="block h-1.5 rounded-full" style={{ width: `${logW(o.notes, max)}%`, background: c }} /></span>
                <span className="w-16 text-right font-mono text-sm text-soft tabular-nums">{num(o.notes)}</span>
              </span>
              <span className="col-span-2 flex gap-4 text-xs text-muted lg:contents">
                {([["soul", o.soul], ["learned", o.learnings], ["retros", o.retros]] as const).map(([l, n]) => (
                  <span key={l} className={cx("font-mono tabular-nums lg:text-right lg:text-sm", n ? "text-soft" : "text-faint")}>{num(n)}<span className="ml-1 font-sans text-muted lg:hidden">{l}</span></span>))}
                <span className="truncate lg:text-sm">{o.machines.join(" · ")}</span>
              </span>
              <span className="hidden text-right text-sm text-muted lg:block">{ago(when(o.newest))}</span>
            </button>
          );
        })}
      </div>
      {!list.length && <State>No oracle by that name. The list holds oracles with a ψ vault on the hub; the Family page lists every oracle the lineage scan knows.</State>}
      {!all && !q && list.length > 60 && <div className="mt-4"><Btn onClick={() => setAll(true)}>Show all {num(list.length)}</Btn></div>}
    </>
  );
}

/** The newest artifacts as one row that scrolls sideways: a glance, not a gallery (each oracle's page has its own). */
function Strip({ items, onOracle }: { items: Artifact[]; onOracle: (name: string) => void }) {
  return (
    <div className="-mx-5 flex snap-x gap-3 overflow-x-auto px-5 pb-2 [scrollbar-width:thin] sm:mx-0 sm:px-0">
      {items.map(a => (
        <button key={a.id} type="button" onClick={() => onOracle(a.oracle)} title={`${a.title} · open ${a.oracle}`}
          className="group w-40 flex-none snap-start overflow-hidden rounded-xl border border-line bg-panel text-left hover:border-line-strong">
          <div className="aspect-square overflow-hidden bg-deep"><Show a={a} /></div>
          <div className="px-2.5 py-2"><div className="line-clamp-2 text-xs font-semibold break-words text-text group-hover:text-accent">{a.title}</div>
            <div className="mt-0.5 truncate text-xs text-muted">{a.oracle} · {ago(a.at)}</div></div>
        </button>
      ))}
    </div>
  );
}
