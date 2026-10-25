// Keep a hit (Nat, 2026-10-25: "store ... what human find or interesting on", "add tag label like digger"): a note and
// tags on the message being read. Saved through the hub's own tools: relic_found (on the search's trace chain, so
// Asked and relic_asked tell it later) and relic_tag (the labels, read back with relic_tags or the Asked page).
import { useEffect, useState } from "react";
import { get, tool } from "../api";
import { Close } from "./Icons";
import { Btn, inputCls } from "./ui";

interface Tags { target: string; tags: string[]; notes: { at: string; note: string }[] }

export function Keep({ link, query, parent, title }: { link: string; query: string; parent?: string; title: string }) {
  const [tags, setTags] = useState<Tags | null>(null);
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState(""), [add, setAdd] = useState("");
  const [busy, setBusy] = useState(false), [msg, setMsg] = useState<string | null>(null);
  useEffect(() => { setTags(null); setOpen(false); setMsg(null); get<Tags>(`/api/tags?target=${encodeURIComponent(link)}`).then(setTags).catch(() => {}); }, [link]);
  const words = (v: string) => v.split(/[,\s]+/).map(x => x.trim().replace(/^#/, "")).filter(Boolean);
  const save = async () => {
    setBusy(true); setMsg(null);
    try {
      const t = words(add);
      if (parent) await tool("relic_found", { parent, goal: query, found: note.trim() || title, links: [link] });
      if (t.length || note.trim()) {
        const r = await tool<Tags>("relic_tag", { target: link, add: t.length ? t : ["kept"], ...(note.trim() ? { note: note.trim() } : {}) });
        setTags(v => ({ ...(v ?? { notes: [] }), ...r, notes: [...(v?.notes ?? []), ...(note.trim() ? [{ at: new Date().toISOString(), note: note.trim() }] : [])] }));
      } else {
        const r = await tool<Tags>("relic_tag", { target: link, add: ["kept"] });
        setTags(v => ({ ...(v ?? { notes: [] }), ...r }));
      }
      setNote(""); setAdd(""); setOpen(false); setMsg("Kept: it is on this search's chain and under its tags (Asked → Found & tags).");
    } catch (e) { setMsg(String((e as Error).message)); } finally { setBusy(false); }
  };
  const drop = async (t: string) => { try { const r = await tool<Tags>("relic_tag", { target: link, remove: [t] }); setTags(v => ({ ...(v ?? { notes: [] }), ...r })); } catch (e) { setMsg(String((e as Error).message)); } };
  return (
    <div className="border-b border-line px-5 py-2.5">
      <div className="flex flex-wrap items-center gap-1.5">
        {(tags?.tags ?? []).map(t => (
          <span key={t} className="inline-flex items-center gap-1 rounded-md bg-accent-wash py-0.5 pr-1 pl-2 text-xs font-semibold text-accent">#{t}
            <button type="button" onClick={() => drop(t)} aria-label={`Remove the tag ${t}`} className="grid size-5 place-items-center rounded text-accent/70 hover:text-accent"><Close size={12} /></button></span>))}
        {!open && <button type="button" onClick={() => setOpen(true)} className="inline-flex min-h-9 items-center rounded-lg px-2 text-xs font-semibold text-accent hover:bg-raised">{tags?.tags.length ? "+ tag or note" : "Keep this hit: note and tags"}</button>}
      </div>
      {tags?.notes.length ? <p className="m-0 mt-1 text-xs text-muted">“{tags.notes[tags.notes.length - 1].note}”</p> : null}
      {open && (
        <form className="mt-2 flex flex-col gap-2" onSubmit={e => { e.preventDefault(); save(); }}>
          <input autoFocus value={note} onChange={e => setNote(e.target.value)} placeholder="Why it matters (optional)" aria-label="A note" className={inputCls + " h-9 text-xs"} />
          <input value={add} onChange={e => setAdd(e.target.value)} placeholder="tags, comma or space: rustfs, backup, idea" aria-label="Tags" className={inputCls + " h-9 font-mono text-xs"} />
          <div className="flex gap-2"><Btn primary type="submit" disabled={busy}>{busy ? "Keeping…" : "Keep"}</Btn><Btn type="button" onClick={() => setOpen(false)}>Cancel</Btn></div>
        </form>
      )}
      {msg && <p role="status" className="m-0 mt-1 text-xs text-muted">{msg}</p>}
    </div>
  );
}
