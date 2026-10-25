import { useState, type ComponentType, type ReactNode } from "react";
import { Drawer } from "../components/Drawer";
import { usePoll } from "../api";
import { ago, bkk, bytes, clock, compact, num, secs, sum } from "../format";
import { Badge, HealthCard, levelText, levelWord, type Level } from "../components/HealthCard";
import { Arrow, Disk, Machine, Pulse, Search, Shield, Vector } from "../components/Icons";
import { syncChip } from "../components/sync";
import { Resources } from "../components/Resources";
import { cx, Stat as Kpi } from "../components/ui";
import type { JobEvent, Queries, Status } from "../types";

/* Home: the glance page inside the hub's shell. The direction contract for the whole hub is in web/index.html. */

interface Check { key: string; title: string; level: Level; text: string; command?: string; big?: ReactNode; icon: ComponentType<{ size?: number }> }

function checks(s: Status, evs: JobEvent[]): Check[] {
  const out: Check[] = [];
  // a copy (COPY.json) gets no pushes, backups or seals: those checks belong to the live hub, not to it
  for (const m of s.copy ? [] : Object.keys({ ...s.machines, ...s.versions }).filter(m => !m.endsWith("-import")).sort()) {
    const f = s.freshness.machines[m] ?? {}, c = syncChip(f.sync), age = f.push_age_s;
    const level: Level = c.tone === "bad" ? "failed" : age == null ? "unknown" : age > 1800 ? "warning" : c.tone === "ok" ? "ok" : "unknown";
    out.push({ key: "m-" + m, title: m, level, icon: Machine, big: age == null ? "unknown" : secs(age),
      text: c.tone === "bad" ? `Its chain reports ${c.text}: what it holds and what the hub holds differ.` :
        age != null && age > 1800 ? `No push for ${secs(age)}; the chain pushes every 10 minutes.` :
          `Pushed ${ago(f.pushed_at)}; its chain says ${c.text}.`,
      command: level === "ok" ? undefined : `ssh ${m} tail -20 ~/Library/Logs/relic-chain.log` });
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
    text: b?.at ? `Snapshot of ${bytes(b.bytes)} on ${b.host}, restore-tested; the next one runs at 03:30.` : "No snapshot of the hub exists yet.",
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
  const same = (a: typeof evs[number], b: typeof evs[number]) => a.verb === b.verb && (a.message ?? a.host) === (b.message ?? b.host);
  const open = failed.filter(f => !day.some(e => e.state === "done" && same(e, f) && Date.parse(e.at) > Date.parse(f.at)));
  out.push({ key: "jobs", title: "Jobs, 24 h", icon: Pulse, level: open.length ? "failed" : evs.length ? "ok" : "unknown",
    big: `${day.length - failed.length}/${day.length}`,
    text: open.length ? `${open.length} failed; the newest: ${open[0].verb} at ${bkk(open[0].at)}. ${open[0].message ?? ""}` :
      `Pushes, index runs, embeds and backups all finished${failed.length ? ` (${failed.length} failed, then ran fine again: ${failed[0].verb} at ${bkk(failed[0].at)}, ${failed[0].message ?? failed[0].host ?? ""})` : ""}.${s.jobs.running.length ? ` Running now: ${s.jobs.running.map(j => j.verb).join(", ")}.` : ""}` });
  return out;
}

const rank: Record<Level, number> = { failed: 0, warning: 1, unknown: 2, ok: 3 };

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
function Searched({ q, search }: { q: Queries | null; search: (q: string) => void }) {
  if (!q) return null;
  const real = (r: { query: string; client?: string | null; tool?: string }) => r.query && r.query.length < 70 && !(r.client ?? "").startsWith("eval");
  const top = q.top.filter(t => real(t)).slice(0, 24);
  const recent = [...new Map([...(q.searches ?? []).map(r => ({ ...r, tool: "relic_search" })), ...q.last].filter(r => r.tool === "relic_search" && real(r)).map(r => [r.query.trim(), r] as const)).values()].slice(0, 8);
  if (!top.length && !recent.length) return null;
  const max = Math.max(...top.map(t => t.n), 1);
  const size = (n: number) => (n / max > 0.66 ? "text-lg font-bold text-text" : n / max > 0.33 ? "text-base font-semibold text-soft" : "text-sm text-muted");
  return (
    <section className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
      <div className="rounded-2xl border border-line bg-panel px-6 py-5">
        <h2 className="m-0 mb-4 text-base font-bold text-text">Searched most</h2>
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-2">
          {top.map(t => (
            <button key={t.query} type="button" onClick={() => search(t.query)} title={`asked ${t.n} times`}
              className={cx("rounded-md px-1 py-0.5 text-left leading-snug transition-colors hover:bg-raised hover:text-accent", size(t.n))}>
              {t.query}<sup className="ml-0.5 font-mono text-xs font-normal text-faint">{t.n}</sup>
            </button>
          ))}
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

        {!s.copy && (bad.length > 0 || s.warnings.length > 0) && (
          <div className="mt-8 grid gap-4 md:grid-cols-2">
            {bad.map(c => <HealthCard key={c.key} title={c.title} level={c.level} command={c.command} big={c.big} icon={c.icon}>{c.text}</HealthCard>)}
            {s.warnings.map(w => <HealthCard key={w} title="The hub warns" level="warning">{w}</HealthCard>)}
          </div>
        )}

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

        <Searched q={asked.data} search={search} />

        <Section title="The hub's machine" sub="What the hub holds on white's disk and what it costs the machine right now. The Disk page has the detail.">
          <Resources s={s} />
        </Section>

        <Section title="Machines" sub="Who feeds the hub: what each one sent, when it last pushed, and what its own chain says about the sync.">
          <MachineRows s={s} machines={machines} />
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

        {(s.seal_days?.length ?? 0) > 0 && (
          <Section title="Months" sub="Each Bangkok month seals when it ends. On seal day the hub checks every machine's copy byte for byte, then writes the month down with a fingerprint; a late row adds an amendment, never a rewrite.">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
              {s.seal_days!.map(d => {
                const tone = d.state === "reconciled" ? "border-line bg-panel" : d.state === "blocked" ? "border-danger bg-danger-wash" : d.state === "sealing" ? "border-warning" : "border-dashed border-line-strong";
                const word = d.state === "reconciled" ? "sealed" : d.state === "blocked" ? "blocked" : d.state === "sealing" ? "sealing" : "open";
                const why = d.state === "reconciled" ? `fingerprint ${d.fingerprint}${d.amendments ? ` · ${d.amendments} amendment(s)` : ""}` : [...d.problems, ...d.waiting].join("\n") || "this month is still being written";
                return (
                  <div key={d.month} title={why} className={cx("rounded-xl border px-4 py-3.5", tone)}>
                    <div className="text-base font-bold tabular-nums text-text">{d.month}</div>
                    <div className={cx("text-xs font-semibold", d.state === "reconciled" ? "text-ok" : d.state === "blocked" ? "text-danger" : d.state === "sealing" ? "text-warning" : "text-accent")}>
                      {word}{d.amendments ? ` +${d.amendments}` : ""}
                    </div>
                    <div className="mt-1 truncate font-mono text-xs text-faint">{d.fingerprint ?? (d.state === "open" ? "live" : (d.problems[0] ?? d.waiting[0] ?? "").split(":")[0])}</div>
                    {d.recap && <button type="button" onClick={() => openRecap(d.month)} className="mt-2 -ml-2 flex min-h-11 items-center rounded-lg px-2 text-xs font-semibold text-accent hover:bg-raised">Read the recap</button>}
                  </div>
                );
              })}
            </div>
          </Section>
        )}

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
