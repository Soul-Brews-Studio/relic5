import type { ReactNode } from "react";
import { usePoll } from "../api";
import { ago, bkk, bytes, num, secs, sum } from "../format";
import { Badge, HealthCard, type Level } from "../components/HealthCard";
import { Ring } from "../components/Ring";
import { syncChip } from "../components/Rail";
import { Chip, Lbl } from "../components/ui";
import type { JobEvent, Status } from "../types";

/** The page to open first: is everything collected, searchable and safe, in plain words and big numbers.
 *  Relic Scanner's four pages on one (agent-relic-v3 scanner/: SmartScanView, EmbeddingView, HealthView, BanksView).
 *  Every number comes from GET /api/status (relic_status) or /api/log; an unknown stays "unknown". */

function Title({ eyebrow, title, sub }: { eyebrow: string; title: string; sub: string }) {
  return (
    <div className="mb-5">
      <div className="text-[11px] font-bold tracking-[.2em] text-warning uppercase">{eyebrow}</div>
      <h1 className="m-0 mt-1 font-sans text-4xl font-bold tracking-tight text-text">{title}</h1>
      <p className="m-0 mt-1.5 font-sans text-[15px] text-muted">{sub}</p>
    </div>
  );
}

function Panel({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-2xl border border-line bg-panel p-5 ${className}`}>{children}</div>;
}

function Big({ label, value, color }: { label: string; value: ReactNode; color?: string }) {
  return (
    <div className="min-w-0">
      <Lbl>{label}</Lbl>
      <div className="truncate font-sans text-2xl font-bold tabular-nums" style={{ color: color ?? "var(--text)" }}>{value}</div>
    </div>
  );
}

interface Check { title: string; level: Level; text: string; command?: string; big?: ReactNode }

function checks(s: Status, evs: JobEvent[]): Check[] {
  const out: Check[] = [];
  const fts = s.freshness.fts?.age_s;
  out.push({ title: "Search index", level: fts == null ? "failed" : fts > 3600 ? "warning" : "ok", big: fts == null ? "none" : secs(fts),
    text: fts == null ? "No BM25 index is published: search falls back to slow substring matching." :
      `Rebuilt ${secs(fts)} ago, after the newest push. Everything pushed before then is searchable.`, command: fts != null && fts <= 3600 ? undefined : "relic5 index --wait" });
  const pending = s.watermarks.vectors.pending;
  out.push({ title: "Vectors", level: pending == null ? "unknown" : pending > 0 ? "warning" : "ok", big: num(pending),
    text: pending ? `${num(pending)} messages wait to be embedded; semantic search misses them until then.` : "Every message long enough to embed has a vector.",
    command: pending ? "relic5 embed   # ANE for a small backlog, gb300 for a big one" : undefined });
  const b = s.backup;
  out.push({ title: "Backup", level: !b?.at ? "failed" : (b.age_s ?? 0) > 36 * 3600 ? "warning" : "ok", big: b?.at ? bytes(b.bytes) : "none",
    text: b?.at ? `Last snapshot ${secs(b.age_s)} ago on ${b.host}, restore-tested nightly. ${b.message ?? ""}` : "No snapshot of the hub exists yet.",
    command: !b?.at || (b.age_s ?? 0) > 36 * 3600 ? "bin/relic5-backup   # on m5" : undefined });
  const d = s.store.disk.free_pct;
  out.push({ title: "Disk on the hub", level: d < 10 ? "failed" : d < 20 ? "warning" : "ok", big: `${d}%`,
    text: `${bytes(s.store.disk.free)} free of ${bytes(s.store.disk.total)}; relic5 itself uses ${bytes(s.store.total)}.`, command: d < 20 ? "relic5 gc   # lists what is big, deletes nothing" : undefined });
  const day = evs.filter(e => Date.now() - Date.parse(e.at) < 86400e3), failed = day.filter(e => e.state === "error");
  out.push({ title: "Jobs, last 24 h", level: failed.length ? "failed" : "ok", big: `${day.length - failed.length}/${day.length}`,
    text: failed.length ? `${failed.length} failed; newest: ${failed[0].verb} at ${bkk(failed[0].at)}, ${failed[0].message ?? ""}` :
      `${day.length} pushes, indexes, embeds and backups, none failed.${s.jobs.running.length ? ` Running now: ${s.jobs.running.map(j => j.verb).join(", ")}.` : ""}` });
  return out;
}

function MachineCard({ s, m }: { s: Status; m: string }) {
  const f = s.freshness.machines[m] ?? {}, x = s.machines[m] ?? {}, v = s.versions[m] ?? {}, c = syncChip(f.sync);
  const imported = m.endsWith("-import");
  const level: Level = imported ? "ok" : c.tone === "bad" ? "failed" : (f.push_age_s ?? 1e9) > 1800 ? "warning" : c.tone === "ok" ? "ok" : "unknown";
  return (
    <Panel className="flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <Badge level={level} />
        <div className="min-w-0">
          <div className="truncate font-sans text-[15px] font-semibold">{m}</div>
          <div className="text-[10px] text-faint">{imported ? "one-time import, no chain" : `${v.os ?? "unknown os"} · relic-scan ${v["relic-scan"] ?? "unknown"}`}</div>
        </div>
        {!imported && <span className="ml-auto"><Chip tone={c.tone}>{c.text}</Chip></span>}
      </div>
      <div className="grid grid-cols-3 gap-3">
        <Big label="messages" value={num(x.text?.rows)} />
        <Big label="tool calls" value={num(x.tools?.rows)} />
        <Big label="thinking" value={num(x.thinking?.rows)} color="var(--user)" />
      </div>
      <div className="border-t border-line pt-3 font-sans text-[12px] leading-relaxed text-muted">
        <div>Last push: <span className="text-soft">{ago(f.pushed_at)}</span></div>
        <div>Newest message: <span className="text-soft">{ago(f.newest_ts)}</span> ({bkk(f.newest_ts)})</div>
        <div>Stored on the hub: <span className="text-soft">{bytes(sum(s.store.parts[m]))}</span></div>
      </div>
    </Panel>
  );
}

export function OverviewView({ s, on }: { s: Status; on: boolean }) {
  const log = usePoll<JobEvent[]>("/api/log?n=300", 30000, on);
  const sessions = usePoll<{ total: number }>("/api/sessions?limit=0", 0, on);
  const list = checks(s, log.data ?? []);
  const attention = list.filter(c => c.level !== "ok").length + s.warnings.length;
  const text = s.rows.text ?? 0;
  // Messages the month manifests counted at the last index, against messages now; BM25 counts chunks, not messages.
  const indexed = s.watermarks.index.rows ?? 0;
  const chunks = Object.entries(s.watermarks.fts.rows).filter(([k]) => k.startsWith("prose_")).reduce((a, [, v]) => a + v, 0);
  const vectors = sum(s.watermarks.vectors.tables);
  const machines = Object.keys({ ...s.machines, ...s.versions }).sort((a, b) => (s.machines[b]?.text?.rows ?? 0) - (s.machines[a]?.text?.rows ?? 0));
  const sealed = s.months.list.filter(m => m.sealed && m.rows.text > 0).length;
  return (
    <div className="mx-auto flex max-w-[1400px] flex-col gap-10 px-6 py-7 font-sans">
      <section>
        <Title eyebrow="One look" title="Overview" sub="What the hub holds, whether every machine is in, and what needs a hand." />
        <Panel className="flex items-center gap-5">
          <Badge level={attention ? "warning" : "ok"} size="lg" />
          <div className="min-w-0">
            <div className="text-xl font-semibold">{attention ? `${attention} thing${attention > 1 ? "s" : ""} need${attention > 1 ? "" : "s"} attention` : "All good"}</div>
            <div className="text-[13px] text-muted">{attention ? "The cards below say what and how to fix it." : `Every machine synced, search is current, the hub is backed up. Read ${new Date().toLocaleTimeString()}.`}</div>
            {s.warnings.map(w => <div key={w} className="mt-1 font-mono text-[11px] text-warning">{w}</div>)}
          </div>
          <div className={`ml-auto text-[11px] font-bold tracking-[.16em] ${attention ? "text-warning" : "text-accent"}`}>{attention ? `${attention} ATTENTION` : "READY"}</div>
        </Panel>
      </section>

      <section className="grid gap-5 lg:grid-cols-[auto_auto_minmax(0,1fr)] lg:items-center">
        <Ring frac={text ? indexed / text : null} value={num(indexed)} of={`of ${num(text)} · ${num(chunks)} chunks`} label="searchable" color="var(--assistant)" />
        <Ring frac={text ? vectors / text : null} value={num(vectors)} of={`of ${num(text)} · ${num(s.watermarks.vectors.pending)} pending`} label="embedded" color="var(--user)" />
        <Panel>
          <div className="mb-3 text-[15px] font-semibold">What is in the hub</div>
          {([
            ["Sessions", sessions.data ? num(sessions.data.total) : "unknown"],
            ["Messages (folded, each once)", num(s.rows.text)],
            ["Tool calls", num(s.rows.tools)],
            ["Thinking blocks", num(s.rows.thinking)],
            ["Months", `${s.months.list.filter(m => m.rows.text > 0).length} (${sealed} sealed, ${s.months.open ?? "none"} open)`],
            ["Last indexed", `${bkk(s.watermarks.fts.at ? new Date(s.watermarks.fts.at.replace(/^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2}).*/, "$1-$2-$3T$4:$5:$6Z")).toISOString() : null)} (+07)`],
            ["On disk", bytes(s.store.total)],
          ] as [string, string][]).map(([k, v]) => (
            <div key={k} className="flex justify-between gap-4 border-b border-line py-2 text-[13px] last:border-b-0">
              <span className="text-muted">{k}</span><b className="font-mono tabular-nums text-text">{v}</b>
            </div>
          ))}
        </Panel>
      </section>

      <section>
        <Title eyebrow="Diagnostics" title="Health" sub="Each check in plain words, with the command that fixes it when it is not OK." />
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {list.map(c => <HealthCard key={c.title} title={c.title} level={c.level} command={c.command} big={c.big}>{c.text}</HealthCard>)}
        </div>
      </section>

      <section>
        <Title eyebrow="Sources" title="Machines" sub="Who feeds the hub: what each one sent, when it last pushed, and its own sync verdict." />
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{machines.map(m => <MachineCard key={m} s={s} m={m} />)}</div>
      </section>
    </div>
  );
}
