import { useEffect, useRef, useState } from "react";
import { get } from "../api";
import { bkk } from "../format";
import type { Hit, SearchResult, ShowResult } from "../types";
import { Drawer } from "../components/Drawer";
import { Btn, Chip, cx, Field, Hint, inputCls, Loading, Marked, State, Toolbar, Who } from "../components/ui";

export interface SearchState { q: string; horizon: string; with: string; repo: string }

function HitRow({ h, q, active, onOpen }: { h: Hit; q: string; active: boolean; onOpen: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { if (active) ref.current?.scrollIntoView({ block: "nearest" }); }, [active]);
  return (
    <div ref={ref} onClick={onOpen} className={cx("cursor-pointer border-b border-line px-4 py-3 hover:bg-panel", active && "bg-accent-wash")}>
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1.5 text-[11px] text-muted">
        <span className="font-bold tabular-nums text-accent">{h.score.toFixed(2)}</span>
        <time>{bkk(h.ts)}</time><Who role={h.role} /><Chip>{h.layer}</Chip>
        <span className="truncate">{h.session_name || h.title || h.repo_key}</span>
        <code className="text-faint">{h.session_uuid.slice(0, 8)}</code>
        <span>{h.machines.join(", ")}</span>
      </header>
      <div className="mt-1.5 line-clamp-4 whitespace-pre-wrap break-words text-xs text-soft"><Marked text={h.text_snippet} q={q} /></div>
    </div>
  );
}

/** The message and three on each side, in the drawer (relic_show). */
function Context({ r, q }: { r: ShowResult; q: string }) {
  const one = (m: ShowResult["target"], target = false) => (
    <div key={m.ts + m.role + (target ? "t" : "")} className={cx("px-4 pt-2.5 pb-2", target && "border-l-2 border-accent bg-accent-wash")}>
      <div className="flex gap-3 text-[10px] text-muted"><time>{bkk(m.ts)}</time><Who role={m.role} /><span>{(m.machines ?? []).join(", ")}</span></div>
      <div className="mt-1 whitespace-pre-wrap break-words text-xs text-soft"><Marked text={m.text ?? ""} q={q} /></div>
    </div>
  );
  return <>{r.before.map(m => one(m))}{one(r.target, true)}{r.after.map(m => one(m))}</>;
}

export function SearchView({ st, setSt, machine, focusKey }:
  { st: SearchState; setSt: (s: SearchState) => void; machine: string; focusKey: number }) {
  const [draft, setDraft] = useState(st);
  const [res, setRes] = useState<SearchResult | null>(null);
  const [ms, setMs] = useState(0);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [active, setActive] = useState(-1);
  const [open, setOpen] = useState<{ hit: Hit; show: ShowResult | null; err?: string } | null>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => { input.current?.focus(); }, [focusKey]);
  useEffect(() => { setDraft(st); if (st.q) run(st); }, [st.q, st.horizon, st.with, st.repo]);   // eslint-disable-line

  async function run(s: SearchState) {
    const p = new URLSearchParams({ q: s.q, limit: "40" });
    if (s.horizon) p.set("horizon", s.horizon);
    if (s.with) p.set("with", s.with);
    if (s.repo) p.set("repo", s.repo);
    setBusy(true); setErr(null);
    const t = performance.now();
    try { setRes(await get<SearchResult>("/api/search?" + p)); setActive(-1); }
    catch (e) { setErr(String((e as Error).message)); }
    finally { setMs(Math.round(performance.now() - t)); setBusy(false); }
  }
  async function openHit(h: Hit) {
    setOpen({ hit: h, show: null });
    try { setOpen({ hit: h, show: await get<ShowResult>(`/api/show?id=${encodeURIComponent(h.link)}&before=3&after=3`) }); }
    catch (e) { setOpen({ hit: h, show: null, err: String((e as Error).message) }); }
  }

  const hits = (res?.hits ?? []).filter(h => !machine || h.machines.includes(machine));
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (open || (e.target as HTMLElement).tagName === "INPUT") return;
      if (e.key === "j") setActive(a => Math.min(a + 1, hits.length - 1));
      if (e.key === "k") setActive(a => Math.max(a - 1, 0));
      if (e.key === "Enter" && hits[active]) openHit(hits[active]);
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  });

  return (
    <>
      <Toolbar onSubmit={() => draft.q.trim() && setSt({ ...draft, q: draft.q.trim() })}>
        <Field label="query — every word must occur (Thai works)" wide htmlFor="q">
          <input id="q" ref={input} type="search" className={inputCls} spellCheck={false} autoComplete="off" placeholder="wordcloud facebook"
            value={draft.q} onChange={e => setDraft({ ...draft, q: e.target.value })} />
        </Field>
        <Field label="horizon" htmlFor="hz">
          <select id="hz" className={inputCls} value={draft.horizon} onChange={e => setDraft({ ...draft, horizon: e.target.value })}>
            <option value="">widen 7d → archive</option>{["7d", "15d", "1m", "3m", "archive"].map(h => <option key={h}>{h}</option>)}
          </select>
        </Field>
        <Field label="layers" htmlFor="with">
          <select id="with" className={inputCls} value={draft.with} onChange={e => setDraft({ ...draft, with: e.target.value })}>
            <option value="">prose</option><option value="tools">+ tools</option><option value="thinking">+ thinking</option><option value="all">all</option>
          </select>
        </Field>
        <Field label="repo" htmlFor="repo">
          <input id="repo" className={inputCls} placeholder="any" value={draft.repo} onChange={e => setDraft({ ...draft, repo: e.target.value })} />
        </Field>
        <Btn primary type="submit">Search</Btn>
      </Toolbar>
      {busy && <Loading />}
      <Hint>{res
        ? `${hits.length} hits${machine ? ` on ${machine}` : ""} · horizon ${res.horizon} (tried ${res.horizons_tried.join(" → ")}) · months ${res.searched_months.join(", ") || "none"} · ${ms} ms${res.fallback ? " · " + res.fallback : ""}`
        : "results come from every machine, folded once per message · keyword (BM25 + exact phrase); semantic search runs through the MCP shim on a Mac"}</Hint>
      {err && <State error>{err}</State>}
      {res && !hits.length && <State>no match</State>}
      {hits.map((h, i) => <HitRow key={h.uid + i} h={h} q={st.q} active={i === active} onOpen={() => { setActive(i); openHit(h); }} />)}
      <Drawer open={!!open} onClose={() => setOpen(null)}
        title={open ? <>{open.hit.session_name || open.hit.repo_key} <code className="text-faint">{open.hit.session_uuid.slice(0, 8)}</code></> : ""}
        note={open?.hit.link} onCopy={() => open && navigator.clipboard.writeText(open.hit.link)}>
        {open?.err ? <State error>{open.err}</State> : open?.show ? <Context r={open.show} q={st.q} /> : <Loading />}
      </Drawer>
    </>
  );
}
