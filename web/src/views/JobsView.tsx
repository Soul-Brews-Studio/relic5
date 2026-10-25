import { usePoll } from "../api";
import { ago, bkk, bytes, clock, num } from "../format";
import { DataTable } from "../components/DataTable";
import { Card, Chip, Hint, Lbl, PageHead, SectionHead, Stat, State, Stats, type Tone } from "../components/ui";
import type { JobEvent, Status } from "../types";

const tone = (s: JobEvent["state"]): Tone => (s === "error" ? "bad" : s === "done" ? "ok" : "warn");
const word = (e: JobEvent) => (e.state === "error" ? "failed" : e.state === "done" ? "done" : e.state === "start" ? "started" : "running");
const same = (a: JobEvent, b: JobEvent) => a.verb === b.verb && (a.message ?? a.host) === (b.message ?? b.host);
/** a failure the same job on the same machine has since run clean past is recovered (Home uses the same rule) */
const recovered = (f: JobEvent, evs: JobEvent[]) => evs.some(e => e.state === "done" && same(e, f) && Date.parse(e.at) > Date.parse(f.at));
const amount = (e: JobEvent) => e.done == null ? "" : e.unit === "bytes" ? bytes(e.done) : `${num(e.done)} ${e.unit ?? ""}`;

/** A running job as relic3's RelicBar drew it (DashboardView.swift: current run row): what, whose, how far. */
function RunCard({ e }: { e: JobEvent }) {
  const frac = e.done != null && e.total ? Math.min(1, e.done / e.total) : null;
  return (
    <Card className="mb-3">
      <div className="flex flex-wrap items-baseline gap-3">
        <b className="text-sm">{e.verb}</b><Chip tone="live">{word(e)}</Chip>
        <Chip>{e.host ?? "unknown host"}{e.pid ? ` · pid ${e.pid}` : ""}</Chip>
        <span className="text-xs text-muted">since {ago(e.at)}</span>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded bg-raised">
        {frac == null ? <div className="loading-bar h-full" /> : <div className="h-full bg-accent" style={{ width: `${frac * 100}%` }} />}
      </div>
      <div className="mt-2 text-xs text-muted">
        {frac == null ? (e.done != null ? `${num(e.done)} ${e.unit ?? ""} so far, total unknown` : "no progress reported yet")
          : `${num(e.done)} of ${num(e.total)} ${e.unit ?? ""} · ${Math.round(frac * 100)}%`}
        {e.message ? ` · ${e.message}` : ""}
      </div>
    </Card>
  );
}

export function JobsView({ s, on }: { s: Status | null; on: boolean }) {
  const log = usePoll<JobEvent[]>("/api/log?n=300", 15000, on);
  const evs = log.data ?? [];
  const day = evs.filter(e => Date.now() - Date.parse(e.at) < 86400e3);
  const fails = day.filter(e => e.state === "error"), open = fails.filter(f => !recovered(f, evs));
  const failed = open.length;
  const lastErr = s?.jobs.last_error, lastOk = lastErr ? recovered(lastErr as JobEvent, evs) : false;
  const running = s ? s.jobs.running.length : null;
  return (
    <>
      <PageHead title="Jobs" sub="Every push, index run, embed and backup, from the hub's job log. A failure stays here until the same job runs clean." />
      <Stats>
        <Stat label="Running" value={running ?? "unknown"} tone={running ? "live" : undefined} />
        <Stat label="Done · 24 h" value={day.filter(e => e.state === "done").length} />
        <Stat label="Failed, still open" value={failed} tone={failed ? "bad" : undefined} note={fails.length > failed ? `${fails.length - failed} recovered since` : undefined} />
        <Stat label={lastOk ? "Last error, since recovered" : "Last error"} value={lastErr ? lastErr.verb : "none"} tone={lastErr && !lastOk ? "bad" : undefined}
          note={lastErr ? `${bkk(lastErr.at)} ${lastErr.message ?? ""}` : undefined} />
      </Stats>
      <SectionHead>Current run</SectionHead>
      {s?.jobs.running.length ? s.jobs.running.map(e => <RunCard key={e.job} e={e} />) : <State>nothing running · index, embed and push each write a start, progress and done line</State>}
      <SectionHead>Recent entries</SectionHead>
      {log.error && <State error>{log.error}</State>}
      <DataTable rows={evs} rowKey={e => e.job} cols={[
        { key: "at", head: "at (+07)", w: "w-36", cell: e => <time>{bkk(e.at)}</time> },
        { key: "v", head: "job", w: "w-36", cell: e => <b className="text-text">{e.verb}</b> },
        { key: "s", head: "state", w: "w-36", cell: e => e.state === "done" ? <span className="text-muted">done</span> : <Chip tone={e.state === "error" && recovered(e, evs) ? "dim" : tone(e.state)}>{word(e)}{e.rc ? ` · rc ${e.rc}` : ""}{e.state === "error" && recovered(e, evs) ? " · recovered" : ""}</Chip> },
        { key: "h", head: "host", w: "w-44", cell: e => e.host ?? "" },
        { key: "d", head: "amount", num: true, w: "w-32", cell: e => amount(e) },
        { key: "m", head: "message", lead: true, cell: e => e.message ?? "", title: e => e.message ?? "" },
      ]} />
      <Hint><Lbl>source</Lbl> last event of each job, from logs/jobs.jsonl (relic3 JobEvent) · {evs.length} jobs · read {clock(log.at)}</Hint>
    </>
  );
}
