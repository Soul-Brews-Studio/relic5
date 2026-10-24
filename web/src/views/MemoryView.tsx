import { useMemo, useState } from "react";
import { get, usePoll } from "../api";
import { ago, bkk, num } from "../format";
import { Drawer } from "../components/Drawer";
import { Search } from "../components/Icons";
import { Btn, cx, inputCls, Loading, Marked, State } from "../components/ui";
import type { ShowResult } from "../types";

interface Note { uid: string; link: string; ts: string; type: string; project: string; title: string; description: string; machines: string[]; home: string }
interface Listing { notes: Note[]; types: Record<string, number>; projects: Record<string, number> }

const TYPE_WORD: Record<string, string> = { feedback: "rules", project: "decisions", reference: "references", user: "about Nat", note: "untyped" };
const TYPE_TONE: Record<string, string> = { feedback: "text-accent", project: "text-assistant", reference: "text-user", user: "text-tool", note: "text-muted" };
const PAGE = 80;

/** The agents' memory notes on their own (memory.py, GET /api/memory): every project's one-fact rules, decisions and
 *  references, filtered as you type, by kind and by project; a click reads the whole note. */
export function MemoryView() {
  const p = usePoll<Listing>("/api/memory", 60000);
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const [project, setProject] = useState("");
  const [shown, setShown] = useState(PAGE);
  const [open, setOpen] = useState<{ n: Note; show: ShowResult | null; err?: string } | null>(null);

  const list = useMemo(() => {
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    return (p.data?.notes ?? []).filter(n => (!type || n.type === type) && (!project || n.project === project) &&
      words.every(w => (n.title + " " + n.description + " " + n.project).toLowerCase().includes(w)));
  }, [p.data, q, type, project]);

  async function read(n: Note) {
    setOpen({ n, show: null });
    try { setOpen({ n, show: await get<ShowResult>(`/api/show?id=${encodeURIComponent(n.link)}`) }); }
    catch (e) { setOpen({ n, show: null, err: String((e as Error).message) }); }
  }

  if (p.error && !p.data) return <State error>{p.error}</State>;
  if (!p.data) return <Loading />;
  const total = p.data.notes.length;
  const chip = (on: boolean) => cx("rounded-full border px-3.5 py-1.5 text-[13px] font-semibold", on ? "border-accent-dim bg-accent-dim text-accent-ink" : "border-line text-soft hover:border-line-strong hover:text-text");
  return (
    <>
      <div className="border-b border-line bg-panel px-6 pt-6 pb-5 font-sans">
        <h2 className="m-0 text-[22px] font-bold tracking-tight text-text">Memory notes</h2>
        <p className="m-0 mt-1 max-w-[70ch] text-[14px] text-muted">
          {num(total)} one-fact notes that agents keep per project: the rules Nat set, the decisions made, where things live. Collected from every machine's <code className="text-[12px]">~/.claude*/projects/*/memory</code>.
        </p>
        <label className="relative mt-5 flex items-center">
          <span className="pointer-events-none absolute left-4 text-muted"><Search size={18} /></span>
          <input type="search" value={q} onChange={e => { setQ(e.target.value); setShown(PAGE); }} placeholder="filter by words in the title or description"
            aria-label="Filter memory notes" spellCheck={false}
            className="h-12 w-full rounded-xl border border-line bg-deep pr-4 pl-11 text-[15px] text-text placeholder:text-faint hover:border-line-strong focus:border-accent focus:outline-none" />
        </label>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <button type="button" className={chip(!type)} onClick={() => setType("")}>all {num(total)}</button>
          {Object.entries(p.data.types).sort((a, b) => b[1] - a[1]).map(([t, n]) => (
            <button key={t} type="button" className={chip(type === t)} onClick={() => { setType(type === t ? "" : t); setShown(PAGE); }}>
              {TYPE_WORD[t] ?? t} <span className="font-normal opacity-70">{num(n)}</span>
            </button>
          ))}
          <select aria-label="Project" value={project} onChange={e => { setProject(e.target.value); setShown(PAGE); }} className={inputCls + " ml-auto w-72"}>
            <option value="">every project ({Object.keys(p.data.projects).length})</option>
            {Object.entries(p.data.projects).map(([pr, n]) => <option key={pr} value={pr}>{pr} · {n}</option>)}
          </select>
        </div>
      </div>
      <div className="border-b border-line bg-panel px-6 py-2.5 text-[12px] text-muted">{num(list.length)} notes{q || type || project ? " match" : ""} · newest first · GET /api/memory</div>
      {list.length === 0 && <State>no note matches</State>}
      {list.slice(0, shown).map(n => (
        <button key={n.uid} type="button" onClick={() => read(n)} className="block w-full cursor-pointer border-b border-line px-6 py-4 text-left font-sans hover:bg-panel">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-[12px] text-muted">
            <span className={cx("font-semibold", TYPE_TONE[n.type])}>{TYPE_WORD[n.type] ?? n.type}</span>
            <b className="text-[14px] font-semibold text-text"><Marked text={n.title} q={q} /></b>
            <span>{n.project}</span><span title={bkk(n.ts)}>{ago(n.ts)}</span><span>{n.machines.join(", ")}</span>
          </div>
          <div className="mt-1.5 line-clamp-2 max-w-[110ch] text-[13px] leading-relaxed text-soft"><Marked text={n.description} q={q} /></div>
        </button>
      ))}
      {list.length > shown && <div className="px-6 py-5"><Btn type="button" onClick={() => setShown(shown + PAGE * 2)}>Show {num(Math.min(PAGE * 2, list.length - shown))} more</Btn></div>}
      <Drawer open={!!open} onClose={() => setOpen(null)} title={open?.n.title ?? ""} note={open ? `${open.n.project} · ${TYPE_WORD[open.n.type] ?? open.n.type} · ${bkk(open.n.ts)}` : ""}
        onCopy={() => open && navigator.clipboard.writeText(open.n.link)}>
        {open?.err ? <State error>{open.err}</State> : open?.show ?
          <div className="px-6 pt-4 font-sans text-[14px] leading-relaxed whitespace-pre-wrap text-soft">{open.show.target.text}</div> : <Loading />}
      </Drawer>
    </>
  );
}
