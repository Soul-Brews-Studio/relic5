import { useEffect, useRef, useState } from "react";
import { get } from "../api";
import { bkk } from "../format";
import type { Hit, SearchResult, ShowResult } from "../types";
import { Drawer } from "../components/Drawer";
import { Btn, Chip, cx, Hint, inputCls, Loading, Marked, Seg, State, Who } from "../components/ui";
import { Search } from "../components/Icons";
import { usePoll } from "../api";
import type { Queries } from "../types";

export interface SearchState { q: string; horizon: string; with: string; repo: string }

function HitRow({ h, q, active, onOpen }: { h: Hit; q: string; active: boolean; onOpen: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { if (active) ref.current?.scrollIntoView({ block: "nearest" }); }, [active]);
  return (
    <div ref={ref} onClick={onOpen} className={cx("cursor-pointer border-b border-line px-6 py-4 hover:bg-panel", active && "bg-accent-wash")}>
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1.5 text-[11px] text-muted">
        <span className="font-bold tabular-nums text-accent">{h.score.toFixed(2)}</span>
        <time>{bkk(h.ts)}</time>
        {h.layer === "memory" ? <Chip tone="ok">{h.role.replace("memory-", "")}</Chip> : <><Who role={h.role} /><Chip>{h.layer}</Chip></>}
        <span className="truncate font-semibold text-soft">{h.layer === "memory" ? h.title : h.session_name || h.title || h.repo_key}</span>
        <code className="text-faint">{h.layer === "memory" ? h.session_uuid.replace(/^memory:-(opt-Code|Users-[^-]+-Code)-github-com-/, "") : h.session_uuid.slice(0, 8)}</code>
        <span>{h.machines.join(", ")}</span>
      </header>
      <div className="mt-2 line-clamp-4 max-w-[110ch] whitespace-pre-wrap break-words font-sans text-[13px] leading-relaxed text-soft"><Marked text={h.text_snippet} q={q} /></div>
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

/** Before the first search: what this box reaches, and the questions people actually asked (GET /api/queries). */
function Empty({ pick, memory }: { pick: (q: string) => void; memory: () => void }) {
  const q = usePoll<Queries>("/api/queries", 0);
  // real searches only: the eval runs (client "eval") ask hundreds of known-item fragments
  const asked = [...new Set((q.data?.last ?? []).filter(r => r.tool === "relic_search" && r.client !== "eval" && r.query && r.query.length < 60)
    .map(r => r.query.trim()))].slice(0, 8);
  const chip = "rounded-full border border-line bg-panel px-3.5 py-1.5 text-[13px] text-soft hover:border-accent hover:text-text";
  return (
    <div className="mx-auto max-w-[760px] px-6 py-14 font-sans">
      <h2 className="m-0 text-[26px] font-bold tracking-tight text-text">Everything every machine said, in one box.</h2>
      <p className="m-0 mt-2 max-w-[60ch] text-[15px] leading-relaxed text-muted">Keyword search over every session on m5, white and mba, each message counted once. It starts with the last 7 days and widens until it finds enough. Press <kbd className="rounded border border-line px-1 text-[12px]">/</kbd> from anywhere.</p>
      {asked.length > 0 && <>
        <h3 className="m-0 mt-9 text-[13px] font-semibold text-muted">Asked before</h3>
        <div className="mt-3 flex flex-wrap gap-2">{asked.map(a => <button key={a} type="button" className={chip} onClick={() => pick(a)}>{a}</button>)}</div>
      </>}
      <h3 className="m-0 mt-9 text-[13px] font-semibold text-muted">Or look in the memory notes</h3>
      <p className="m-0 mt-2 text-[14px] text-soft">The one-fact rules, decisions and references agents keep per project, separate from the talk.</p>
      <button type="button" className={chip + " mt-3"} onClick={memory}>Search memory notes</button>
    </div>
  );
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

  const go = (next: SearchState) => { setDraft(next); if (next.q.trim()) setSt({ ...next, q: next.q.trim() }); };
  return (
    <>
      <form onSubmit={e => { e.preventDefault(); go(draft); }} className="border-b border-line bg-panel px-6 pt-6 pb-5 font-sans">
        <div className="flex gap-3">
          <label className="relative flex min-w-0 flex-1 items-center">
            <span className="pointer-events-none absolute left-4 text-muted"><Search size={18} /></span>
            <input id="q" ref={input} type="search" spellCheck={false} autoComplete="off" aria-label="Search every machine"
              placeholder={draft.with === "memory" ? "a rule, a decision, a reference…" : "what was said — every word must occur; Thai works"}
              value={draft.q} onChange={e => setDraft({ ...draft, q: e.target.value })}
              className="h-12 w-full rounded-xl border border-line bg-deep pr-4 pl-11 text-[15px] text-text placeholder:text-faint hover:border-line-strong focus:border-accent focus:outline-none" />
          </label>
          <Btn primary type="submit" className="!h-12 !rounded-xl !px-6 !text-[13px]">Search</Btn>
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-3 text-[12px] text-muted">
          <span className="flex items-center gap-2.5">When
            <Seg label="Horizon" value={draft.horizon} onChange={v => go({ ...draft, horizon: v })}
              options={[{ value: "", label: "auto" }, { value: "7d", label: "7d" }, { value: "15d", label: "15d" }, { value: "1m", label: "1m" }, { value: "3m", label: "3m" }, { value: "archive", label: "all" }]} /></span>
          <span className="flex items-center gap-2.5">What
            <Seg label="Layers" value={draft.with} onChange={v => go({ ...draft, with: v })}
              options={[{ value: "", label: "talk" }, { value: "tools", label: "+ tools" }, { value: "thinking", label: "+ thinking" }, { value: "memory", label: "memory notes" }, { value: "all", label: "everything" }]} /></span>
          <span className="flex items-center gap-2.5">Repo
            <input aria-label="Repo" className={inputCls + " w-44 font-mono"} placeholder="any" value={draft.repo}
              onChange={e => setDraft({ ...draft, repo: e.target.value })} onBlur={() => draft.repo !== st.repo && go(draft)} /></span>
        </div>
      </form>
      {busy && <Loading />}
      {!st.q && !res && <Empty pick={q => go({ ...draft, q })} memory={() => go({ ...draft, with: "memory" })} />}
      {res && <Hint>{`${hits.length} hits${machine ? ` on ${machine}` : ""} · horizon ${res.horizon} (tried ${res.horizons_tried.join(" → ")}) · months ${res.searched_months.join(", ") || "none"} · ${ms} ms${res.fallback ? " · " + res.fallback : ""}`}</Hint>}
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
