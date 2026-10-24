import type { ComponentType, ReactNode } from "react";
import { usePoll } from "../api";
import { ago, bkk, bytes, compact, num, secs, sum } from "../format";
import { Badge, HealthCard, levelText, levelWord, type Level } from "../components/HealthCard";
import { Arrow, Disk, Machine, Pulse, Search, Shield, Vector } from "../components/Icons";
import { pill, TopBar } from "../components/TopBar";
import { Ring } from "../components/Ring";
import { syncChip } from "../components/sync";
import { cx } from "../components/ui";
import type { JobEvent, Status } from "../types";

/* DIRECTION CONTRACT (impeccable, surface round seed fab56f46, card "Relic Scanner, grown up")
   THESIS: one page answers "is everything in, current and safe?"; a problem is never quieter than the good news.
   OWN-WORLD: the hub's Structor Dark/Paper tokens; rounded panels, drawn icons, big sans numerals, mono for data only.
   STORY: Nat reads one sentence, sees any failing check first and in red, then the two rings and the machines.
   FIRST VIEWPORT: verdict sentence at display size, failing cards directly under it, then the rings and the ledger.
   FORM: Relic Scanner's four pages (Smart Scan, Embedding, Health, Banks) as one scroll, no rail, no tabs.
   FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md,
   and every shipping raster carrying its provenance. */

interface Check { key: string; title: string; level: Level; text: string; command?: string; big?: ReactNode; icon: ComponentType<{ size?: number }> }

function checks(s: Status, evs: JobEvent[]): Check[] {
  const out: Check[] = [];
  for (const m of Object.keys({ ...s.machines, ...s.versions }).filter(m => !m.endsWith("-import")).sort()) {
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
  out.push({ key: "backup", title: "Backup", icon: Shield, level: !b?.at ? "failed" : stale ? "warning" : "ok", big: b?.at ? secs(b.age_s) : "none",
    text: b?.at ? `Snapshot of ${bytes(b.bytes)} on ${b.host}, restore-tested; the next one runs at 03:30.` : "No snapshot of the hub exists yet.",
    command: stale ? "bin/relic5-backup && bin/relic5-restore-test" : undefined });
  const d = s.store.disk.free_pct;
  out.push({ key: "disk", title: "Disk on white", icon: Disk, level: d < 10 ? "failed" : d < 20 ? "warning" : "ok", big: `${d}%`,
    text: `${bytes(s.store.disk.free)} free of ${bytes(s.store.disk.total)}; relic5 uses ${bytes(s.store.total)} of it.`,
    command: d < 20 ? "relic5 gc" : undefined });
  const sv = s.seals?.verify, sealedN = Object.values(s.seals?.machines ?? {}).reduce((a, x) => a + x.sealed, 0);
  out.push({ key: "seals", title: "Sealed months", icon: Shield, level: !sv ? "unknown" : sv.problems.length ? "failed" : "ok",
    big: sv ? `${sv.checked - sv.problems.length}/${sv.checked}` : "none",
    text: !sv ? "No machine has sent a seal yet." : sv.problems.length ? `${sv.problems.length} sealed month(s) changed on the hub: ${sv.problems[0]}` :
      `${sealedN} machine-months sealed; each one's parts still hold the rows they were sealed with.`,
    command: sv?.problems.length ? "relic5 seals --verify" : undefined });
  const day = evs.filter(e => Date.now() - Date.parse(e.at) < 86400e3), failed = day.filter(e => e.state === "error");
  out.push({ key: "jobs", title: "Jobs, 24 h", icon: Pulse, level: failed.length ? "failed" : evs.length ? "ok" : "unknown",
    big: `${day.length - failed.length}/${day.length}`,
    text: failed.length ? `${failed.length} failed; the newest: ${failed[0].verb} at ${bkk(failed[0].at)}. ${failed[0].message ?? ""}` :
      `Pushes, index runs, embeds and backups all finished.${s.jobs.running.length ? ` Running now: ${s.jobs.running.map(j => j.verb).join(", ")}.` : ""}` });
  return out;
}

const rank: Record<Level, number> = { failed: 0, warning: 1, unknown: 2, ok: 3 };

function Section({ title, sub, children }: { title: string; sub: string; children: ReactNode }) {
  return (
    <section className="mt-16">
      <h2 className="m-0 font-sans text-[28px] font-bold tracking-tight text-text">{title}</h2>
      <p className="m-0 mt-1 mb-6 max-w-[62ch] font-sans text-[15px] text-muted">{sub}</p>
      {children}
    </section>
  );
}

function MachineCard({ s, m }: { s: Status; m: string }) {
  const f = s.freshness.machines[m] ?? {}, x = s.machines[m] ?? {}, v = s.versions[m] ?? {}, c = syncChip(f.sync);
  const imported = m.endsWith("-import");
  const level: Level = imported ? "ok" : c.tone === "bad" ? "failed" : (f.push_age_s ?? 1e9) > 1800 ? "warning" : c.tone === "ok" ? "ok" : "unknown";
  const Stat = ({ label, value, color }: { label: string; value: number | undefined; color?: string }) => (
    <div className="min-w-0" title={`${label}: ${num(value)}`}><div className="font-sans text-[12px] text-muted">{label}</div>
      <div className="font-sans text-[22px] font-bold tabular-nums" style={{ color: color ?? "var(--text)" }}>{compact(value)}</div></div>
  );
  return (
    <div className={cx("flex flex-col gap-4 rounded-2xl border p-5", level === "failed" ? "border-danger bg-danger-wash" : level === "warning" ? "border-warning" : "border-line bg-panel")}>
      <div className="flex items-center gap-3">
        <Badge level={level} />
        <div className="min-w-0">
          <div className="truncate font-sans text-[15px] font-semibold">{m}</div>
          <div className="truncate font-sans text-[12px] text-faint" title={v.os}>{imported ? "one-time import, no chain" : `relic-scan ${v["relic-scan"] ?? "unknown"}`}</div>
        </div>
        {!imported && <span className={cx("ml-auto font-sans text-[12px] font-semibold whitespace-nowrap", levelText(level))}>{c.text}</span>}
      </div>
      <div className="grid grid-cols-3 gap-3">
        <Stat label="messages" value={x.text?.rows} />
        <Stat label="tool calls" value={x.tools?.rows} />
        <Stat label="thinking" value={x.thinking?.rows} color="var(--user)" />
      </div>
      <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 border-t border-line pt-3 font-sans text-[13px]">
        <dt className="text-muted">Last push</dt><dd className="m-0 text-soft">{ago(f.pushed_at)}</dd>
        <dt className="text-muted">Newest message</dt><dd className="m-0 text-soft">{ago(f.newest_ts)} <span className="text-faint">({bkk(f.newest_ts)})</span></dd>
        <dt className="text-muted">On the hub</dt><dd className="m-0 text-soft">{bytes(sum(s.store.parts[m]))}</dd>
        <dt className="text-muted">Sealed</dt><dd className="m-0 text-soft">{s.seals?.machines[m] ? `${s.seals.machines[m].sealed} months · ${s.seals.machines[m].resealed ? `${s.seals.machines[m].resealed} resealed · ` : ""}since ${bkk(s.seals.machines[m].newest_sealed_at)}` : imported ? "no chain" : "not yet (relic-scan before seals)"}</dd>
      </dl>
    </div>
  );
}

export function GlancePage({ s, error, at, theme, setTheme }:
  { s: Status | null; error: string | null; at: Date | null; theme: "dark" | "paper"; setTheme: (t: "dark" | "paper") => void }) {
  const log = usePoll<JobEvent[]>("/api/log?n=300", 30000);
  const sessions = usePoll<{ total: number; events: number }>("/api/sessions?limit=0", 0);
  const top = <TopBar theme={theme} setTheme={setTheme} note={error ? "hub unreachable" : at ? `read ${at.toLocaleTimeString()} · every 15 s` : "reading…"}
    link={<a href="#tab=live" className={pill}>Open the hub <Arrow size={16} /></a>} />;
  if (!s) return <div className="h-dvh overflow-y-auto">{top}<p className="mx-auto max-w-[1200px] px-5 py-16 font-sans text-lg text-muted">{error ?? "Reading the hub…"}</p></div>;

  const list = checks(s, log.data ?? []).sort((a, b) => rank[a.level] - rank[b.level]);
  const bad = list.filter(c => c.level === "failed" || c.level === "warning");
  const level: Level = bad.some(c => c.level === "failed") ? "failed" : bad.length || s.warnings.length ? "warning" : "ok";
  const text = s.rows.text ?? 0, indexed = s.watermarks.index.rows ?? 0, vectors = sum(s.watermarks.vectors.tables);
  const months = s.months.list.filter(m => m.rows.text > 0);
  const machines = Object.keys({ ...s.machines, ...s.versions }).sort((a, b) => (s.machines[b]?.text?.rows ?? 0) - (s.machines[a]?.text?.rows ?? 0));
  const machinesOk = list.filter(c => c.key.startsWith("m-") && c.level === "ok").length, machinesAll = list.filter(c => c.key.startsWith("m-")).length;
  const verdict = level === "ok"
    ? `All in. ${machinesOk} of ${machinesAll} machines synced, searchable to ${secs(s.freshness.fts?.age_s)} ago, backed up ${secs(s.backup?.age_s)} ago.`
    : `${bad.length + s.warnings.length} ${bad.length + s.warnings.length === 1 ? "thing needs" : "things need"} you: ${bad.map(c => c.title).join(", ") || "see the hub's warnings"}.`;

  return (
    <div className="h-dvh overflow-y-auto">
      {top}
      <main className="mx-auto max-w-[1200px] px-5 pt-10 pb-20 font-sans">
        <section className="flex items-start gap-5">
          <Badge level={level} size="lg" />
          <div className="min-w-0">
            <h1 className={cx("m-0 max-w-[24ch] text-[clamp(28px,4.4vw,52px)] leading-[1.08] font-bold tracking-[-0.025em] text-balance", level === "ok" ? "text-text" : levelText(level))}>{verdict}</h1>
            <p className="m-0 mt-3 text-[15px] text-muted">{levelWord(level)} · {sessions.data ? `${num(sessions.data.events)} transcript events in ${num(sessions.data.total)} sessions` : `${num(text)} messages`} from {machines.length} sources · {s.months.list.filter(m => m.sealed && m.rows.text > 0).length} sealed months, {s.months.open ?? "no"} open</p>
          </div>
        </section>

        {(bad.length > 0 || s.warnings.length > 0) && (
          <div className="mt-8 grid gap-4 md:grid-cols-2">
            {bad.map(c => <HealthCard key={c.key} title={c.title} level={c.level} command={c.command} big={c.big} icon={c.icon}>{c.text}</HealthCard>)}
            {s.warnings.map(w => <HealthCard key={w} title="The hub warns" level="warning">{w}</HealthCard>)}
          </div>
        )}

        <section className="mt-12 grid grid-cols-2 items-center justify-items-center gap-4 sm:gap-6 lg:grid-cols-[auto_auto_minmax(0,1fr)] lg:justify-items-stretch">
          <Ring frac={text ? indexed / text : null} value={num(indexed)} of={`of ${num(text)} messages`} label="searchable" color="var(--assistant)" />
          <Ring frac={text ? vectors / text : null} value={num(vectors)} of={`${num(s.watermarks.vectors.pending)} waiting`} label="embedded" color="var(--user)" />
          <div className="col-span-2 w-full rounded-2xl border border-line bg-panel p-5 lg:col-span-1">
            <h2 className="m-0 mb-2 text-[15px] font-semibold text-text">In the hub</h2>
            {([
              ["Sessions", sessions.data ? num(sessions.data.total) : "unknown"],
              ["Transcript events (every .jsonl record)", sessions.data ? num(sessions.data.events) : "unknown"],
              ["Records, each counted once", num((s.rows.text ?? 0) + (s.rows.tools ?? 0) + (s.rows.thinking ?? 0))],
              ["Messages, each counted once", num(s.rows.text)],
              ["Tool calls", num(s.rows.tools)],
              ["Thinking blocks", num(s.rows.thinking)],
              ["Memory notes (rules, decisions)", s.memory && Object.keys(s.memory).length ? `${num(sum(s.memory))} · ${Object.entries(s.memory).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${k} ${v}`).join(" · ")}` : "none yet"],
              ["Months", `${months[0]?.month ?? "?"} to ${months[months.length - 1]?.month ?? "?"}`],
              ["On disk", bytes(s.store.total)],
            ] as [string, string][]).map(([k, v]) => (
              <div key={k} className="flex justify-between gap-4 border-b border-line py-2 text-[14px] last:border-b-0">
                <span className="text-muted">{k}</span><b className="font-mono text-[13px] tabular-nums text-text">{v}</b>
              </div>
            ))}
          </div>
        </section>

        <Section title="Every check" sub="Failing and late checks come first. When one is not OK, its card says why and gives the command that fixes it.">
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {list.filter(c => !c.key.startsWith("m-")).map(c => <HealthCard key={c.key} title={c.title} level={c.level} command={c.command} big={c.big} icon={c.icon}>{c.text}</HealthCard>)}
          </div>
        </Section>

        {(s.seal_days?.length ?? 0) > 0 && (
          <Section title="Months" sub="Each Bangkok month seals when it ends. On seal day the hub checks every machine's copy byte for byte, then writes the month down with a fingerprint; a late row adds an amendment, never a rewrite.">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
              {s.seal_days!.map(d => {
                const tone = d.state === "reconciled" ? "border-accent-dim bg-accent-wash" : d.state === "blocked" ? "border-danger bg-danger-wash" : d.state === "sealing" ? "border-warning" : "border-line bg-panel";
                const word = d.state === "reconciled" ? "sealed" : d.state === "blocked" ? "blocked" : d.state === "sealing" ? "sealing" : "open";
                const why = d.state === "reconciled" ? `fingerprint ${d.fingerprint}${d.amendments ? ` · ${d.amendments} amendment(s)` : ""}` : [...d.problems, ...d.waiting].join("\n") || "this month is still being written";
                return (
                  <div key={d.month} title={why} className={cx("rounded-xl border px-3.5 py-3", tone)}>
                    <div className="text-[15px] font-semibold tabular-nums text-text">{d.month}</div>
                    <div className={cx("text-[12px] font-semibold", d.state === "reconciled" ? "text-accent" : d.state === "blocked" ? "text-danger" : d.state === "sealing" ? "text-warning" : "text-muted")}>
                      {word}{d.amendments ? ` +${d.amendments}` : ""}
                    </div>
                    <div className="mt-1 truncate font-mono text-[10px] text-faint">{d.fingerprint ?? (d.state === "open" ? "live" : (d.problems[0] ?? d.waiting[0] ?? "").split(":")[0])}</div>
                  </div>
                );
              })}
            </div>
          </Section>
        )}

        <Section title="Machines" sub="Who feeds the hub: what each one sent, when it last pushed, and what its own chain says about the sync.">
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{machines.map(m => <MachineCard key={m} s={s} m={m} />)}</div>
        </Section>

        <p className="mt-16 text-[12px] text-faint">Every number on this page comes from GET /api/status (relic_status), /api/log and /api/sessions on white; unknown means the hub did not say.</p>
      </main>
    </div>
  );
}
