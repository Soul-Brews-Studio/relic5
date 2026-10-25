// Every open problem in one floating card, on every page (Nat, 2026-10-25: "all warning should floating card? like
// incident and issues?"). Failing and late checks (the same checks as Home's), then the hub's own warnings that no
// check already says, then a failed poll. Each one with its severity and the command that fixes it. It folds to a
// small badge; a new set of problems opens it again. It sits bottom-right, above the phone's tab bar.
import { useEffect, useMemo, useState } from "react";
import { usePoll } from "../api";
import { checks, rank } from "../views/GlancePage";
import type { JobEvent, Status } from "../types";
import { Badge, type Level } from "./HealthCard";
import { Close } from "./Icons";
import { cx } from "./ui";

export interface Incident { key: string; title: string; level: Level; text: string; command?: string }

/** A hub warning that a failing check already tells (the backup, a failed job) is not said twice. */
function said(w: string, bad: { key: string }[]) {
  const has = (k: string) => bad.some(c => c.key === k);
  return (/backup/i.test(w) && has("backup")) || (/^last \S+ failed/.test(w) && has("jobs"));
}

/** The open incidents: the floating card and the Incidents page read the same list. */
export function useIncidents(s: Status | null, error: string | null): Incident[] {
  const log = usePoll<JobEvent[]>("/api/log?n=300", 30000);
  return useMemo<Incident[]>(() => {
    const out: Incident[] = [];
    if (error) out.push({ key: "poll", title: "The hub did not answer", level: "failed", text: error });
    if (!s || s.copy) return out;
    const bad = checks(s, log.data ?? []).filter(c => c.level === "failed" || c.level === "warning").sort((a, b) => rank[a.level] - rank[b.level]);
    for (const c of bad) out.push({ key: c.key, title: c.title, level: c.level, text: c.text, command: c.command });
    for (const w of s.warnings) if (!said(w, bad)) out.push({ key: "w:" + w, title: "The hub warns", level: "warning", text: w });
    return out;
  }, [s, error, log.data]);
}

/** One incident: its severity dot, title, the whole text (the card clamps it to three lines), the fixing command. */
export function IncidentRow({ i, full }: { i: Incident; full?: boolean }) {
  const [copied, setCopied] = useState(false);
  return (
    <li className={cx("flex gap-3 border-b border-line last:border-b-0", full ? "px-5 py-4" : "px-4 py-3")}>
      <span className={cx("mt-1.5 size-2.5 flex-none rounded-full", i.level === "failed" ? "bg-danger" : "bg-warning")} aria-label={i.level === "failed" ? "failed" : "warning"} />
      <div className="min-w-0 flex-1">
        <div className="text-sm font-semibold text-text">{i.title}</div>
        <p className={cx("m-0 mt-0.5 text-sm break-words text-soft", !full && "line-clamp-3")} title={full ? undefined : i.text}>{i.text}</p>
        {i.command && (
          <button type="button" onClick={() => { navigator.clipboard.writeText(i.command!); setCopied(true); setTimeout(() => setCopied(false), 1500); }}
            className="mt-2 flex w-full min-w-0 items-center gap-2 rounded-lg bg-deep px-2.5 py-2 text-left font-mono text-xs text-soft hover:text-text" title="Copy the command">
            <span className="text-faint">$</span><span className={cx("min-w-0 flex-1", full ? "break-all" : "truncate")}>{i.command}</span>
            <span className="flex-none font-sans font-semibold text-accent">{copied ? "copied" : "copy"}</span>
          </button>
        )}
      </div>
    </li>
  );
}

export function Incidents({ s, error, open, hidden }: { s: Status | null; error: string | null; open: () => void; hidden?: boolean }) {
  const items = useIncidents(s, error);
  const sig = items.map(i => i.key + i.level).join("|");
  const [folded, setFolded] = useState(() => localStorage.getItem("relic5-incidents") === sig && sig !== "");
  useEffect(() => { setFolded(localStorage.getItem("relic5-incidents") === sig); }, [sig]);   // a new set opens again
  const fold = (v: boolean) => { localStorage.setItem("relic5-incidents", v ? sig : ""); setFolded(v); };
  if (!items.length || hidden) return null;
  const worst: Level = items.some(i => i.level === "failed") ? "failed" : "warning";
  const tone = worst === "failed" ? "border-danger" : "border-warning";
  if (folded) return (
    <button type="button" onClick={() => fold(false)} aria-label={`${items.length} open incidents: show them`}
      className={cx("fixed right-4 bottom-20 z-40 inline-flex min-h-11 items-center gap-2 rounded-full border bg-panel py-1.5 pr-4 pl-1.5 text-sm font-semibold text-text shadow-[var(--shadow-pop)] sm:bottom-4", tone)}>
      <Badge level={worst} /> {items.length} open
    </button>
  );
  return (
    <aside aria-label="Open incidents" role="status"
      className={cx("fixed right-4 bottom-20 z-40 flex max-h-[min(70dvh,560px)] w-[380px] max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-2xl border bg-panel shadow-[var(--shadow-pop)] sm:bottom-4", tone)}>
      <header className="flex items-center gap-3 border-b border-line px-4 py-3">
        <a href="#tab=incidents" onClick={e => { e.preventDefault(); open(); }} className="text-sm font-bold text-text hover:text-accent" title="Open every incident on its own page">
          {items.length} open {items.length === 1 ? "incident" : "incidents"}
        </a>
        <span className={cx("text-xs font-semibold", worst === "failed" ? "text-danger" : "text-warning")}>{worst === "failed" ? "something failed" : "needs a look"}</span>
        <a href="#tab=incidents" onClick={e => { e.preventDefault(); open(); }} className="ml-auto inline-flex min-h-9 items-center rounded-lg px-2 text-xs font-semibold text-accent hover:bg-raised">See all</a>
        <button type="button" onClick={() => fold(true)} aria-label="Fold the incidents" className="grid size-9 place-items-center rounded-lg text-muted hover:bg-raised hover:text-text"><Close size={16} /></button>
      </header>
      <ol className="m-0 flex list-none flex-col overflow-y-auto p-0">
        {items.map(i => <IncidentRow key={i.key} i={i} />)}
      </ol>
    </aside>
  );
}
