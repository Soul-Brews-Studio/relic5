import { useState, type ComponentType, type ReactNode } from "react";
import { Drawer } from "../components/Drawer";
import { usePoll } from "../api";
import { ago, bkk, bytes, clock, compact, num, secs, sum } from "../format";
import { Badge, HealthCard, levelText, levelWord, type Level } from "../components/HealthCard";
import { Arrow, Disk, Lock, Machine, Pulse, Search, Shield, Vector } from "../components/Icons";
import { syncChip } from "../components/sync";
import { Resources } from "../components/Resources";
import { HourBars, Latency } from "../components/AskedCharts";
import { cx, Stat as Kpi } from "../components/ui";
import type { AskedStats, HomeRow, JobEvent, Queries, Status } from "../types";

/* Home: the glance page inside the hub's shell. The direction contract for the whole hub is in web/index.html. */

export interface Check { key: string; title: string; level: Level; text: string; command?: string; big?: ReactNode; icon: ComponentType<{ size?: number }> }

const WEEK = 7 * 24 * 3600;
// one manual pass per machine (relic4-scan docs/MANUAL.md)
const IMPORT: Record<string, string> = {
  m5: "relic5 import",
  white: "ssh white systemctl --user start relic-chain.service",
  mba: "ssh mba 'RELIC5_MACHINE=mba ~/.local/bin/relic-chain'",
};

export function checks(s: Status, evs: JobEvent[]): Check[] {
  const out: Check[] = [];
  // a copy (COPY.json) gets no pushes, backups or seals: those checks belong to the live hub, not to it
  for (const m of s.copy ? [] : Object.keys({ ...s.machines, ...s.versions }).filter(m => !m.endsWith("-import")).sort()) {
    const f = s.freshness.machines[m] ?? {}, c = syncChip(f.sync), age = f.push_age_s;
    // imports are manual since 2026-10-26 (relic4-scan docs/MANUAL.md): a quiet machine is normal, so only a push older
    // than a week is worth a look, and the hint is that machine's one-pass command, not a 10-minute loop's log
    const level: Level = c.tone === "bad" ? "failed" : age == null ? "unknown" : age > WEEK ? "warning" : "ok";
    out.push({ key: "m-" + m, title: m, level, icon: Machine, big: age == null ? "unknown" : secs(age),
      text: c.tone === "bad" ? `Its last import reports ${c.text}: what it holds and what the hub holds differ.` :
        age != null && age > WEEK ? `No push for ${secs(age)}. Imports are manual: run one to make its newest history searchable.` :
          `Pushed ${ago(f.pushed_at)} (manual imports); ${c.text}.`,
      command: level === "ok" ? undefined : IMPORT[m] ?? `ssh ${m} relic-chain   # one pass, see docs/MANUAL.md` });
  }
  const fts = s.freshness.fts?.age_s;
  out.push({ key: "index", title: "Search index", icon: Search, level: fts == null ? "failed" : fts > 3600 ? "warning" : "ok", big: fts == null ? "none" : secs(fts),
    text: fts == null ? "No BM25 index is published; search falls back to slow substring matching." :
      `Rebuilt ${secs(fts)} ago. Every push before that is searchable.`, command: fts != null && fts <= 3600 ? undefined : "relic5 index --wait" });
  const pending = s.watermarks.vectors.pending;
  out.push({ key: "vectors", title: "Vectors", icon: Vector, level: pending == null ? "unknown" : pending > 0 ? "warning" : "ok", big: num(pending),
    text: pending ? `${num(pending)} messages wait to be embedded; semantic search misses them until then.` : "Every message long enough to embed has a vector.",
    command: pending ? "relic5 embed" : undefined });
  const b = s.backup, stale = !b?.at || (b.age_s ?? 0) > 36 * 3600;
  if (!s.copy) out.push({ key: "backup", title: "Backup", icon: Shield, level: !b?.at ? "failed" : stale ? "warning" : "ok", big: b?.at ? secs(b.age_s) : "none",
    text: b?.at ? `Snapshot of ${bytes(b.bytes)} on ${b.host}, restore-tested. Backups run by hand since 2026-10-26 (no nightly job).` : "No snapshot of the hub exists yet.",
    command: stale ? "bin/relic5-backup && bin/relic5-restore-test" : undefined });
  const d = s.store.disk.free_pct;
  out.push({ key: "disk", title: s.copy ? "Disk on this machine" : "Disk on white", icon: Disk, level: d < 10 ? "failed" : d < 20 ? "warning" : "ok", big: `${d}%`,
    text: `${bytes(s.store.disk.free)} free of ${bytes(s.store.disk.total)}; relic5 uses ${bytes(s.store.total)} of it.`,
    command: d < 20 ? "relic5 gc" : undefined });
  const sv = s.seals?.verify, sealedN = Object.values(s.seals?.machines ?? {}).reduce((a, x) => a + x.sealed, 0);
  out.push({ key: "seals", title: "Sealed months", icon: Shield, level: !sv ? "unknown" : sv.problems.length ? "failed" : "ok",
    big: sv ? `${sv.checked - sv.problems.length}/${sv.checked}` : "none",
    text: !sv ? "No machine has sent a seal yet." : sv.problems.length ? `${sv.problems.length} sealed month(s) changed on the hub: ${sv.problems[0]}` :
      `${sealedN} machine-months sealed; each one's parts still hold the rows they were sealed with.`,
    command: sv?.problems.length ? "relic5 seals --verify" : undefined });
  const day = evs.filter(e => Date.now() - Date.parse(e.at) < 86400e3), failed = day.filter(e => e.state === "error");
  // a failure the same job kind on the same machine has since finished cleanly is recovered, not failing (mba's push
  // failed at 19:31 on 10-24 and pushed fine every pass after; the card stayed red for 24 h)
  // a failure is over when the same job ran fine after it: the same verb, for the same month when the message names one
  // (a recap's "written" never repeats its "no file naming…", so matching whole messages kept a fixed recap red for 24 h)
  const subject = (e: typeof evs[number]) => (e.message ?? "").match(/\b\d{4}-\d{2}\b(?!-\d)/)?.[0] ?? e.host ?? "";
  const same = (a: typeof evs[number], b: typeof evs[number]) => a.verb === b.verb && subject(a) === subject(b);
  const open = failed.filter(f => !day.some(e => e.state === "done" && same(e, f) && Date.parse(e.at) > Date.parse(f.at)));
  out.push({ key: "jobs", title: "Jobs, 24 h", icon: Pulse, level: open.length ? "failed" : evs.length ? "ok" : "unknown",
    big: `${day.length - failed.length}/${day.length}`,
    text: open.length ? `${open.length} failed; the newest: ${open[0].verb} at ${bkk(open[0].at)}. ${open[0].message ?? ""}` :
      `Pushes, index runs, embeds and backups all finished${failed.length ? ` (${failed.length} failed, then ran fine again: ${failed[0].verb} at ${bkk(failed[0].at)}, ${failed[0].message ?? failed[0].host ?? ""})` : ""}.${s.jobs.running.length ? ` Running now: ${s.jobs.running.map(j => j.verb).join(", ")}.` : ""}` });
  return out;
}

export const rank: Record<Level, number> = { failed: 0, warning: 1, unknown: 2, ok: 3 };

function Section({ title, sub, children }: { title: string; sub: string; children: ReactNode }) {
  return (
    <section className="mt-12">
      <h2 className="m-0 text-lg font-bold tracking-[-0.01em] text-text">{title}</h2>
      <p className="m-0 mt-1.5 mb-5 max-w-[75ch] text-sm text-muted">{sub}</p>
      {children}
    </section>
  );
}

/** Every machine as one row (Nat: "this hard too, may be list view?"): the cards made you read three tiles and a
 *  four-line list per machine; a row lines the machines up so the eye compares them down a column. */
function MachineRows({ s, machines }: { s: Status; machines: string[] }) {
  const cell = "border-b border-line px-4 py-3 align-middle [tr:last-child>&]:border-b-0";
  const head = "border-b border-line px-4 py-3 text-xs font-bold tracking-[0.08em] whitespace-nowrap text-muted uppercase";
  return (
    <div className="overflow-x-auto rounded-2xl border border-line bg-panel">
      <table className="w-full min-w-[760px] border-collapse text-sm">
        <thead><tr>
          <th className={head + " text-left"}>Machine</th><th className={head + " text-left"}>Sync</th>
          <th className={head + " text-right"}>Messages</th><th className={head + " text-right"}>Tools</th><th className={head + " text-right"}>Thinking</th>
          <th className={head + " text-left"}>Pushed</th><th className={head + " text-left"}>Newest</th>
          <th className={head + " text-right"}>Size</th><th className={head + " text-left"}>Sealed</th>
        </tr></thead>
        <tbody>{machines.map(m => {
          const f = s.freshness.machines[m] ?? {}, x = s.machines[m] ?? {}, v = s.versions[m] ?? {}, c = syncChip(f.sync), seal = s.seals?.machines[m];
          const imported = m.endsWith("-import");
          const level: Level = imported ? "ok" : c.tone === "bad" ? "failed" : (f.push_age_s ?? 1e9) > 1800 ? "warning" : c.tone === "ok" ? "ok" : "unknown";
          return (
            <tr key={m} className={cx(level === "failed" && "bg-danger-wash", imported && "text-muted")}>
              <td className={cell}><div className="flex items-center gap-3"><Badge level={level} />
                <div className="min-w-0"><div className="font-bold text-text">{m}</div>
                  <div className="truncate text-xs text-muted" title={v.os}>{imported ? "one-time import" : `relic-scan ${(v["relic-scan"] ?? "unknown").replace(/^26\./, "")}`}</div></div></div></td>
              <td className={cell}><span className={cx("text-xs font-semibold whitespace-nowrap", imported ? "text-muted" : levelText(level))}>{imported ? "no chain" : c.text}</span></td>
              <td className={cell + " text-right font-mono tabular-nums text-text"} title={num(x.text?.rows)}>{compact(x.text?.rows)}</td>
              <td className={cell + " text-right font-mono tabular-nums text-soft"} title={num(x.tools?.rows)}>{compact(x.tools?.rows)}</td>
              <td className={cell + " text-right font-mono tabular-nums text-soft"} title={num(x.thinking?.rows)}>{compact(x.thinking?.rows)}</td>
              <td className={cell + " whitespace-nowrap text-soft"}>{ago(f.pushed_at)}</td>
              <td className={cell + " whitespace-nowrap text-soft"} title={bkk(f.newest_ts)}>{ago(f.newest_ts)}</td>
              <td className={cell + " text-right font-mono whitespace-nowrap tabular-nums text-soft"}>{bytes(sum(s.store.parts[m]))}</td>
              <td className={cell + " whitespace-nowrap text-soft"}>{seal ? <>{seal.sealed} months{seal.resealed ? <span className="text-muted"> · {seal.resealed} resealed</span> : null}</> : imported ? "—" : "not yet"}</td>
            </tr>
          );
        })}</tbody>
      </table>
    </div>
  );
}

/** What people and agents searched lately: the most-asked queries as a cloud (size = how often), the newest ones as a
 *  list; a click runs it again (GET /api/queries; the eval runs' known-item fragments are left out). */
/** What a searched string is, by its shape: the cloud's colour says it. */
type Kind = "words" | "thai" | "id";
const KINDS: { k: Kind; label: string; c: string }[] = [
  { k: "words", label: "words", c: "var(--accent)" }, { k: "thai", label: "Thai", c: "var(--ok)" },
  { k: "id", label: "an id or name", c: "var(--amber)" },
];
const KIND = Object.fromEntries(KINDS.map(k => [k.k, k])) as Record<Kind, (typeof KINDS)[number]>;
const kindOf = (q: string): Kind => /[\u0E00-\u0E7F]/.test(q) ? "thai"
  : !/\s/.test(q) && (/\d/.test(q) || /[.\-_/]/.test(q)) ? "id" : "words";

function Asked({ goAsked }: { goAsked: () => void }) {
  const p = usePoll<AskedStats>("/api/asked?hours=24", 60000);
  if (!p.data || !p.data.hours.length) return null;
  const s = p.data;
  return (
    <section className="mt-6 rounded-2xl border border-line bg-panel px-6 py-5">
      <div className="mb-5 flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <h2 className="m-0 text-base font-bold text-text">Asked, the last 24 hours</h2>
        <span className="text-sm text-muted">{num(s.calls)} calls · {num(s.searches)} searches · {s.zero_share == null ? "no searches" : `${Math.round(s.zero_share * 1000) / 10}% found nothing`}
          {s.by_client[0] && ` · most from ${s.by_client[0].client}`}</span>
        <button type="button" onClick={goAsked} className="ml-auto inline-flex min-h-11 items-center gap-1.5 rounded-lg px-2 text-sm font-semibold text-accent hover:bg-raised">Log, chains, saved searches<Arrow size={16} /></button>
      </div>
      <div className="grid gap-8 lg:grid-cols-2"><HourBars s={s} /><Latency s={s} /></div>
    </section>
  );
}

const MON = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** The months as a ledger (Nat, 2026-10-25: "make this better"): one column a month, its bar the messages it holds,
 *  coloured by its seal (sealed, sealing, blocked, open), a lock when sealed and a dot per amendment; one row under
 *  them says everything about the month picked: when it sealed, its fingerprint, amendments, and its recap. */
function MonthLedger({ days, months, openRecap }: { days: NonNullable<Status["seal_days"]>; months: Status["months"]["list"]; openRecap: (m: string) => void }) {
  const rows = new Map(months.map(m => [m.month, m.rows.text]));
  const max = Math.max(1, ...days.map(d => rows.get(d.month) ?? 0));
  const [pick, setPick] = useState(() => [...days].reverse().find(d => d.recap)?.month ?? days[days.length - 1]?.month);
  const [copied, setCopied] = useState(false);
  const d = days.find(x => x.month === pick) ?? days[days.length - 1];
  const fill = (st: string) => (st === "reconciled" ? "var(--ok)" : st === "blocked" ? "var(--danger)" : st === "sealing" ? "var(--warning)" : "var(--accent)");
  const word = (st: string) => (st === "reconciled" ? "sealed" : st === "blocked" ? "blocked" : st === "sealing" ? "sealing" : "open, still being written");
  const sealed = days.filter(x => x.state === "reconciled").length;
  return (
    <div className="rounded-2xl border border-line bg-panel px-5 pt-5 pb-4">
      <div className="mb-4 flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm">
        <b className="text-text">{sealed} of {days.length} sealed</b>
        <span className="inline-flex items-center gap-1.5 text-muted"><i className="inline-block size-2.5 rounded-sm bg-ok" />sealed</span>
        <span className="inline-flex items-center gap-1.5 text-muted"><i className="inline-block size-2.5 rounded-sm border border-dashed border-accent" />open</span>
        <span className="inline-flex items-center gap-1.5 text-muted"><i className="inline-block size-1.5 rounded-full bg-amber" />an amendment</span>
        <span className="ml-auto text-xs text-muted">bar: messages that month</span>
      </div>
      <div className="-mx-5 overflow-x-auto px-5 pb-1 [scrollbar-width:thin]">
        <div role="listbox" aria-label="Months" className="grid min-w-[560px] grid-flow-col auto-cols-fr items-end gap-1.5">
          {days.map(x => {
            const n = rows.get(x.month) ?? 0, h = Math.max(4, Math.round((132 * n) / max)), on = x.month === d?.month, open = x.state === "open";
            return (
              <button key={x.month} type="button" role="option" aria-selected={on} onClick={() => setPick(x.month)}
                title={`${x.month}: ${word(x.state)} · ${num(n)} messages${x.amendments ? ` · ${x.amendments} amendments` : ""}`}
                className={cx("group flex min-w-0 flex-col items-center gap-1.5 rounded-lg px-0.5 pt-1 pb-1.5 transition-colors", on ? "bg-raised" : "hover:bg-raised/60")}>
                <span className="font-mono text-[11px] text-faint tabular-nums">{compact(n)}</span>
                <span className="flex h-[132px] w-full items-end justify-center">
                  <span className="block w-[70%] max-w-9 rounded-t-[4px] transition-[filter] group-hover:brightness-110"
                    style={{ height: h, background: open ? `repeating-linear-gradient(135deg, color-mix(in srgb, ${fill(x.state)} 35%, transparent) 0 4px, transparent 4px 8px)` : `color-mix(in srgb, ${fill(x.state)} ${on ? 85 : 55}%, transparent)`,
                      boxShadow: open ? `inset 0 0 0 1.5px ${fill(x.state)}` : on ? `inset 0 2px 0 ${fill(x.state)}` : undefined }} />
                </span>
                <span className="flex h-3 items-center gap-[3px]" aria-hidden>{Array.from({ length: Math.min(x.amendments, 8) }, (_, i) => <i key={i} className="size-1.5 rounded-full bg-amber" />)}</span>
                <span className={cx("text-xs font-semibold tabular-nums", on ? "text-text" : "text-soft")}>{MON[+x.month.slice(5, 7)]}</span>
                <span className="flex h-4 items-center text-[11px] text-faint tabular-nums">{x.month.slice(5) === "01" || x === days[0] ? `'${x.month.slice(2, 4)}` : x.state === "reconciled" ? <span className="text-ok"><Lock size={12} /></span> : open ? <span className="text-accent">live</span> : ""}</span>
              </button>
            );
          })}
        </div>
      </div>
      {d && (
        <div className="mt-3 flex flex-wrap items-center gap-x-6 gap-y-2 border-t border-line pt-3 text-sm">
          <b className="text-base text-text tabular-nums">{d.month}</b>
          <span className={cx("font-semibold", d.state === "reconciled" ? "text-ok" : d.state === "blocked" ? "text-danger" : d.state === "sealing" ? "text-warning" : "text-accent")}>{word(d.state)}</span>
          <span className="text-soft tabular-nums">{num(rows.get(d.month) ?? 0)} messages</span>
          {d.reconciled_at && <span className="text-muted">sealed {bkk(d.reconciled_at)}</span>}
          {d.amendments > 0 && <span className="text-muted">{d.amendments} {d.amendments === 1 ? "amendment" : "amendments"} (late rows, added, never rewritten)</span>}
          {d.fingerprint && (
            <button type="button" onClick={() => { navigator.clipboard.writeText(d.fingerprint!); setCopied(true); setTimeout(() => setCopied(false), 1500); }}
              className="inline-flex min-h-9 items-center gap-2 rounded-lg bg-deep px-2.5 font-mono text-xs text-soft hover:text-text" title="Copy the fingerprint">
              <span className="text-faint">fingerprint</span>{d.fingerprint}<span className="font-sans font-semibold text-accent">{copied ? "copied" : "copy"}</span>
            </button>
          )}
          {(d.problems.length > 0 || d.waiting.length > 0) && <span className="text-warning">{[...d.problems, ...d.waiting].join(" · ")}</span>}
          {d.recap && <button type="button" onClick={() => openRecap(d.month)} className="ml-auto inline-flex min-h-11 items-center rounded-lg px-3 text-sm font-semibold text-accent hover:bg-raised">Read the {MON[+d.month.slice(5, 7)]} recap</button>}
        </div>
      )}
    </div>
  );
}

/** Whose .claude (GET /api/homes): one row per home and machine, most messages first. */
function Homes() {
  const p = usePoll<{ homes: HomeRow[]; note?: string }>("/api/homes", 300000);
  if (!p.data) return null;
  if (!p.data.homes.length) return <p className="m-0 text-sm text-muted">{p.data.note ?? "No homes yet."}</p>;
  const max = Math.max(1, ...p.data.homes.map(h => h.messages));
  return (
    <div className="overflow-hidden rounded-2xl border border-line bg-panel">
      {p.data.homes.slice(0, 40).map(h => (
        <a key={`${h.machine}|${h.home}`} href={h.home ? `#tab=search&home=${encodeURIComponent(h.home)}` : undefined}
          className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-1 border-b border-line px-5 py-3 last:border-b-0 hover:bg-raised md:grid-cols-[7rem_minmax(0,1fr)_8rem_minmax(0,9rem)_6rem]">
          <span className="text-sm font-semibold text-text">{h.user ?? "unknown"}<span className="ml-2 text-xs font-normal text-muted">{h.machine}</span></span>
          <span className="col-span-2 min-w-0 md:col-span-1">
            <span className="block truncate font-mono text-sm text-soft" title={h.home ?? ""}>{h.label}</span>
            {h.kind !== "user" && <span className={"text-xs " + (h.kind === "project" ? "text-amber" : "text-muted")}>{({ extra: "another home of the same user", project: "a project's own home", mirror: "a mirror copy of another home", backup: "a backup or attic inside a home", export: "an exported home", unknown: "no .claude, .codex or project folder in its path" } as Record<string, string>)[h.kind]}</span>}
          </span>
          <span className="text-right text-sm text-muted tabular-nums md:text-left">{num(h.sessions)} sessions</span>
          <span className="flex items-center gap-2"><span className="h-1.5 min-w-0 flex-1 rounded-full bg-raised"><span className="block h-1.5 rounded-full bg-accent" style={{ width: `${Math.max(2, (100 * Math.log1p(h.messages)) / Math.log1p(max))}%` }} /></span>
            <span className="w-14 text-right font-mono text-xs text-muted tabular-nums">{compact(h.messages)}</span></span>
          <span className="text-right text-xs text-muted">{ago(h.last)}</span>
        </a>
      ))}
    </div>
  );
}

function Searched({ q, search }: { q: Queries | null; search: (q: string) => void }) {
  if (!q) return null;
  // what a person would type: no eval fragments, no message links or bare message ids (a human never typed those)
  const real = (r: { query: string; client?: string | null; tool?: string }) => r.query && r.query.length < 70 && !(r.client ?? "").startsWith("eval")
    && !r.query.startsWith("relic5://") && !/^[0-9a-f]{16,}$/i.test(r.query.trim());
  const top = q.top.filter(t => real(t)).slice(0, 40);
  const recent = [...new Map([...(q.searches ?? []).map(r => ({ ...r, tool: "relic_search" })), ...q.last].filter(r => r.tool === "relic_search" && real(r)).map(r => [r.query.trim(), r] as const)).values()].slice(0, 16);
  if (!top.length && !recent.length) return null;
  const max = Math.max(...top.map(t => t.n), 1);
  // one smooth scale (log of times asked), 14 to 34 px, so the cloud fills the card instead of three small sizes
  const px = (n: number) => 14 + 20 * (Math.log1p(n - 1) / Math.log1p(Math.max(1, max - 1)));
  const kinds = top.reduce((m, t) => m.add(kindOf(t.query)), new Set<Kind>());
  return (
    <section className="mt-6 grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
      <div className="flex flex-col rounded-2xl border border-line bg-panel px-6 py-5">
        <div className="mb-4 flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <h2 className="m-0 text-base font-bold text-text">Searched most</h2>
          {KINDS.filter(k => kinds.has(k.k)).map(k => <span key={k.k} className="inline-flex items-center gap-1.5 text-xs text-muted"><i className="inline-block size-2 rounded-full" style={{ background: k.c }} />{k.label}</span>)}
        </div>
        <div className="flex flex-1 flex-wrap content-center items-baseline gap-x-5 gap-y-2.5">
          {top.map(t => {
            const k = KIND[kindOf(t.query)], w = t.n / max;
            return (
              <button key={t.query} type="button" onClick={() => search(t.query)} title={`${k.label}: asked ${t.n} times`}
                style={{ color: `color-mix(in srgb, ${k.c} ${Math.round(55 + 45 * w)}%, var(--muted))`, fontSize: `${px(t.n)}px`, fontWeight: w > 0.5 ? 700 : w > 0.2 ? 600 : 400 }}
                className="max-w-full rounded-md px-1 py-0.5 text-left leading-tight tracking-[-0.01em] [overflow-wrap:anywhere] transition-[background-color,filter] hover:bg-raised hover:brightness-125">
                {t.query}<sup className="ml-0.5 font-mono text-xs font-normal text-faint">{t.n}</sup>
              </button>
            );
          })}
        </div>
      </div>
      <div className="rounded-2xl border border-line bg-panel px-6 py-5">
        <h2 className="m-0 mb-2 text-base font-bold text-text">Searched lately</h2>
        <ul className="m-0 list-none p-0">
          {recent.map(r => (
            <li key={r.at + r.query} className="border-b border-line last:border-b-0">
              <button type="button" onClick={() => search(r.query)} className="flex min-h-11 w-full items-center gap-3 text-left text-sm">
                <span className="min-w-0 flex-1 truncate text-soft hover:text-accent">{r.query}</span>
                <span className="font-mono text-xs text-faint tabular-nums">{r.hits ?? "?"} hits · {ago(r.at)}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

export function GlancePage({ s, error, at, openHub, search }: { s: Status | null; error: string | null; at: Date | null; openHub: () => void; search: (q: string) => void }) {
  const asked = usePoll<Queries>("/api/queries", 60000);
  const log = usePoll<JobEvent[]>("/api/log?n=300", 30000);
  const [recap, setRecap] = useState<{ month: string; text: string } | null>(null);
  const openRecap = async (month: string) => {
    const r = await fetch(`/api/month-recap?month=${month}`, { credentials: "same-origin" });
    setRecap({ month, text: r.ok ? await r.text() : `no recap for ${month} yet` });
  };
  const sessions = usePoll<{ total: number; events: number; all?: { sessions: number; events: number; subagents: number; subagent_events: number } }>("/api/sessions?limit=0", 0);
  const every = sessions.data?.all;   // every session once, subagents included (top-level alone undercounts by ~30%)
  if (!s) return <p className="py-16 text-lg text-muted">{error ?? "Reading the hub…"}</p>;

  const list = checks(s, log.data ?? []).sort((a, b) => rank[a.level] - rank[b.level]);
  const bad = list.filter(c => c.level === "failed" || c.level === "warning");
  const level: Level = s.copy ? "unknown" : bad.some(c => c.level === "failed") ? "failed" : bad.length || s.warnings.length ? "warning" : "ok";
  const text = s.rows.text ?? 0, indexed = s.watermarks.index.rows ?? 0, vectors = sum(s.watermarks.vectors.tables);
  const months = s.months.list.filter(m => m.rows.text > 0);
  const machines = Object.keys({ ...s.machines, ...s.versions }).sort((a, b) => Number(a.endsWith("-import")) - Number(b.endsWith("-import")) || (s.machines[b]?.text?.rows ?? 0) - (s.machines[a]?.text?.rows ?? 0));
  const machinesOk = list.filter(c => c.key.startsWith("m-") && c.level === "ok").length, machinesAll = list.filter(c => c.key.startsWith("m-")).length;
  const verdict = s.copy ? `A copy of ${s.copy.of}'s hub, as of ${bkk(s.copy.at)} Bangkok (${ago(s.copy.at)}). Search works; nothing new arrives here.`
    : level === "ok"
    ? `All in. ${machinesOk} of ${machinesAll} machines synced, searchable to ${secs(s.freshness.fts?.age_s)} ago, backed up ${secs(s.backup?.age_s)} ago.`
    : `${bad.length + s.warnings.length} ${bad.length + s.warnings.length === 1 ? "thing needs" : "things need"} you: ${bad.map(c => c.title).join(", ") || "see the hub's warnings"}.`;

  const imports = machines.filter(m => m.endsWith("-import")).length;
  const okChecks = list.filter(c => !c.key.startsWith("m-") && c.level === "ok");
  const recentJobs = (log.data ?? []).slice(0, 8);

  return (
    <div className="grid gap-x-10 min-[1500px]:grid-cols-[minmax(0,1fr)_320px]">
      <div className="min-w-0">
        {/* the verdict: one sentence, the badge hung in the margin so the text shares the cards' left edge */}
        <section className="relative lg:pl-0">
          <span className="absolute top-1 -left-[60px] hidden xl:block"><Badge level={level} /></span>
          <h1 className={cx("m-0 max-w-[30ch] text-xl leading-[1.12] font-extrabold tracking-[-0.02em] text-balance lg:text-[40px]", level === "ok" || s.copy ? "text-text" : levelText(level))}>{verdict}</h1>
          <p className="m-0 mt-3 text-base text-muted">{levelWord(level)} · read {clock(at)} · {s.months.list.filter(m => m.sealed && m.rows.text > 0).length} sealed months, {s.months.open ?? "no"} open</p>
          {/* where each machine stands, without scrolling (Panel A) */}
          <div className="mt-5 flex flex-wrap gap-2">
            {list.filter(c => c.key.startsWith("m-")).map(c => (
              <a key={c.key} href={`#tab=live&machine=${c.title}`} className={cx("inline-flex min-h-11 items-center gap-2 rounded-lg border px-3.5 text-sm font-semibold",
                c.level === "ok" ? "border-line text-soft hover:border-line-strong" : c.level === "failed" ? "border-danger text-danger" : "border-warning text-warning")}>
                <span className={cx("size-2 rounded-full", c.level === "ok" ? "bg-ok" : c.level === "failed" ? "bg-danger" : c.level === "warning" ? "bg-warning" : "bg-muted")} />
                {c.title}<span className="font-normal text-muted">{c.big}</span>
              </a>
            ))}
            {imports > 0 && <span className="inline-flex min-h-11 items-center px-1 text-sm text-muted">+ {imports} one-time import{imports === 1 ? "" : "s"}</span>}
          </div>
        </section>


        {/* the four numbers Nat asks for first, on the canvas like relic-scan's strip; colour only when one is short */}
        <section className="mt-12 grid grid-cols-2 gap-x-8 gap-y-8 lg:grid-cols-4">
          <Kpi label="Transcript events" value={every ? compact(every.events) : "unknown"}
            note={every ? `${num(every.events)} records · ${num(every.sessions)} sessions` : undefined} />
          <Kpi label="Indexed" value={compact(indexed)} tone={indexed < text ? "warn" : undefined}
            note={`${num(indexed)} of ${num(text)} messages · ${secs(s.freshness.fts?.age_s)} old`} />
          <Kpi label="Embedded" value={text ? `${Math.floor((vectors / text) * 1000) / 10}%` : compact(vectors)} tone={s.watermarks.vectors.pending ? "warn" : undefined}
            note={`${num(vectors)} vectors · ${num(s.watermarks.vectors.pending)} waiting`} />
          <Kpi label="Backup" value={s.backup?.at ? secs(s.backup.age_s) : "none"} tone={s.backup?.at ? undefined : "bad"}
            note={s.backup?.at ? "old · restore-tested on m5" : "no snapshot yet"} />
        </section>

        {/* what was asked, under the four numbers (Nat, 2026-10-25: "ask under stats"); open problems float in the
            incident card on every page (components/Incidents.tsx) */}
        <Asked goAsked={() => { location.hash = "tab=queries"; }} />
        <Searched q={asked.data} search={search} />

        {(s.seal_days?.length ?? 0) > 0 && (
          <Section title="Months" sub="Each Bangkok month seals when it ends. On seal day the hub checks every machine's copy byte for byte, then writes the month down with a fingerprint; a late row adds an amendment, never a rewrite.">
            <MonthLedger days={s.seal_days!} months={s.months.list} openRecap={openRecap} />
          </Section>
        )}

        <Section title="The hub's machine" sub="What the hub holds on white's disk and what it costs the machine right now. The Disk page has the detail.">
          <Resources s={s} />
        </Section>


        <Section title="Machines" sub="Who feeds the hub: what each one sent, when it last pushed, and what its own chain says about the sync.">
          <MachineRows s={s} machines={machines} />
        </Section>

        <Section title="Where the history comes from" sub="Every .claude (or .codex) folder on each machine: a user's own, an extra home like ~/.claude1, or a project's own .claude. Open one to search only it.">
          <Homes />
        </Section>

        <Section title="Every check" sub="Failing and late checks come first, each with the command that fixes it. The rest are fine.">
          {list.filter(c => !c.key.startsWith("m-") && c.level !== "ok").length > 0 && (
            <div className="mb-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {list.filter(c => !c.key.startsWith("m-") && c.level !== "ok").map(c => <HealthCard key={c.key} title={c.title} level={c.level} command={c.command} big={c.big} icon={c.icon}>{c.text}</HealthCard>)}
            </div>
          )}
          <ul className="m-0 list-none rounded-2xl border border-line bg-panel px-6 py-2">
            {okChecks.map(c => {
              const I = c.icon;
              return (
                <li key={c.key} className="grid min-h-12 grid-cols-[20px_minmax(0,11rem)_auto_minmax(0,1fr)] items-center gap-x-4 border-b border-line py-2.5 last:border-b-0 max-md:grid-cols-[20px_minmax(0,1fr)_auto]">
                  <span className="text-ok"><I size={18} /></span>
                  <span className="truncate text-sm font-semibold text-text">{c.title}</span>
                  <span className="text-right font-semibold text-soft tabular-nums md:text-left">{c.big}</span>
                  <span className="truncate text-sm text-muted max-md:col-span-3 max-md:pl-9">{c.text}</span>
                </li>
              );
            })}
          </ul>
        </Section>


        <details className="group mt-12 rounded-2xl border border-line bg-panel">
          <summary className="flex min-h-14 cursor-pointer list-none items-center gap-3 px-6 text-base font-bold text-text">
            Every count, and where it comes from<span className="ml-auto text-sm font-normal text-muted group-open:hidden">records, tools, thinking, memory, disk</span>
          </summary>
          <div className="border-t border-line px-6 py-3">
            {([
              ["Transcript events (every .jsonl record)", every ? num(every.events) : "unknown", every ? `top-level ${num(sessions.data?.events)} · subagents ${num(every.subagent_events)} · GET /api/sessions` : ""],
              ["Records, each counted once", num((s.rows.text ?? 0) + (s.rows.tools ?? 0) + (s.rows.thinking ?? 0)), "messages + tool calls + thinking, folded across machines"],
              ["Messages", num(s.rows.text), "user and assistant text, cleaned by relic-extract"],
              ["Tool calls", num(s.rows.tools), "one row per call, its result folded in"],
              ["Thinking blocks", num(s.rows.thinking), "only the ones with text"],
              ["Memory notes", s.memory && Object.keys(s.memory).length ? num(sum(s.memory)) : "none yet", s.memory ? Object.entries(s.memory).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${k} ${num(v)}`).join(" · ") : ""],
              ["Months", `${months[0]?.month ?? "?"} to ${months[months.length - 1]?.month ?? "?"}`, `${months.length} with messages`],
              ["On disk", bytes(s.store.total), `white · ${bytes(s.store.disk.free)} free`],
            ] as [string, string, string][]).map(([k, v, why]) => (
              <div key={k} className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-6 border-b border-line py-3 last:border-b-0">
                <span className="text-sm text-soft">{k}<span className="mt-0.5 block text-xs text-muted">{why}</span></span>
                <b className="self-center text-base font-semibold tabular-nums text-text">{v}</b>
              </div>
            ))}
          </div>
        </details>

        <Drawer open={!!recap} onClose={() => setRecap(null)} title={recap ? `${recap.month}: the month recap` : ""}
          note="written by a forked agent from the sealed month only (bin/relic5-month-recap)">
          <div className="max-w-[80ch] px-6 pt-5 pb-6 text-sm leading-relaxed whitespace-pre-wrap text-soft">{recap?.text}</div>
        </Drawer>
        <p className="mt-12 flex flex-wrap items-center gap-4 text-xs text-faint">Every number on this page comes from GET /api/status (relic_status), /api/log, /api/sessions and /api/queries on white; unknown means the hub did not say.
          <button type="button" onClick={openHub} className="flex min-h-11 items-center gap-1.5 rounded-lg border border-line px-3.5 text-sm font-semibold text-soft hover:border-line-strong hover:text-text">Watch it live <Arrow size={16} /></button></p>
      </div>

      {/* the right column on a wide screen: what the hub did lately (relic-scan's "Recent scans") */}
      <aside aria-label="Recent activity" className="hidden min-[1500px]:block">
        <div className="sticky top-4">
          <h2 className="m-0 mb-3 text-xs font-bold tracking-[0.14em] text-muted uppercase">Lately</h2>
          <ul className="m-0 list-none p-0">
            {recentJobs.map(e => (
              <li key={e.job} className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 border-t border-line py-3 text-sm">
                <span className="min-w-0 truncate"><b className={cx("font-semibold", e.state === "error" ? "text-danger" : "text-text")}>{e.verb}</b> <span className="text-muted">· {e.message?.replace(/^machine /, "") ?? e.host}</span></span>
                <span className="text-right text-xs text-muted tabular-nums">{ago(e.at).replace(" ago", "")}</span>
              </li>
            ))}
          </ul>
          <a href="#tab=jobs" className="mt-3 inline-flex min-h-11 items-center gap-1.5 text-sm font-semibold text-accent">All jobs <Arrow size={15} /></a>
        </div>
      </aside>
    </div>
  );
}
