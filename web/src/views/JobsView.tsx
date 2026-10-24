import { usePoll } from "../api";
import { ago, bkk, num } from "../format";
import { DataTable } from "../components/DataTable";
import { Chip, Hint, Lbl, SectionHead, Stat, State, Stats, type Tone } from "../components/ui";
import type { JobEvent, Status } from "../types";

const tone = (s: JobEvent["state"]): Tone => (s === "error" ? "bad" : s === "done" ? "ok" : "warn");
const word = (e: JobEvent) => (e.state === "error" ? "FAILED" : e.state === "done" ? "DONE" : e.state === "start" ? "STARTED" : "RUNNING");

/** A running job as relic3's RelicBar drew it (DashboardView.swift: current run row): what, whose, how far. */
function RunCard({ e }: { e: JobEvent }) {
  const frac = e.done != null && e.total ? Math.min(1, e.done / e.total) : null;
  return (
    <div className="border-b border-line px-4 py-3">
      <div className="flex flex-wrap items-baseline gap-3">
        <b className="text-sm">{e.verb}</b><Chip tone="warn">{word(e)}</Chip>
        <Chip>{e.host ?? "unknown host"}{e.pid ? ` · pid ${e.pid}` : ""}</Chip>
        <span className="text-[11px] text-muted">since {ago(e.at)}</span>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded bg-raised">
        {frac == null ? <div className="loading-bar h-full" /> : <div className="h-full bg-accent" style={{ width: `${frac * 100}%` }} />}
      </div>
      <div className="mt-1 text-[11px] text-muted">
        {frac == null ? (e.done != null ? `${num(e.done)} ${e.unit ?? ""} so far, total unknown` : "no progress reported yet")
          : `${num(e.done)} of ${num(e.total)} ${e.unit ?? ""} · ${Math.round(frac * 100)}%`}
        {e.message ? ` · ${e.message}` : ""}
      </div>
    </div>
  );
}

export function JobsView({ s, on }: { s: Status | null; on: boolean }) {
  const log = usePoll<JobEvent[]>("/api/log?n=300", 15000, on);
  const evs = log.data ?? [];
  const day = evs.filter(e => Date.now() - Date.parse(e.at) < 86400e3);
  const failed = day.filter(e => e.state === "error").length;
  const lastErr = s?.jobs.last_error;
  return (
    <>
      <Stats>
        <Stat label="running" value={s ? s.jobs.running.length : "unknown"} tone="warn" />
        <Stat label="done · 24 h" value={day.filter(e => e.state === "done").length} tone="ok" />
        <Stat label="failed · 24 h" value={failed} tone={failed ? "bad" : undefined} />
        <Stat label="last error" value={lastErr ? lastErr.verb : "none"} tone={lastErr ? "bad" : undefined} note={lastErr ? `${bkk(lastErr.at)} ${lastErr.message ?? ""}` : undefined} />
      </Stats>
      <SectionHead>Current run</SectionHead>
      {s?.jobs.running.length ? s.jobs.running.map(e => <RunCard key={e.job} e={e} />) : <State>nothing running · index, embed and push each write a start, progress and done line</State>}
      <SectionHead>Recent entries</SectionHead>
      {log.error && <State error>{log.error}</State>}
      <DataTable rows={evs} rowKey={e => e.job} cols={[
        { key: "at", head: "at (+07)", cell: e => <time>{bkk(e.at)}</time> },
        { key: "v", head: "job", cell: e => <b>{e.verb}</b> },
        { key: "s", head: "state", cell: e => <Chip tone={tone(e.state)}>{word(e)}</Chip> },
        { key: "rc", head: "rc", num: true, cell: e => e.rc ?? "" },
        { key: "h", head: "host", cell: e => e.host ?? "" },
        { key: "d", head: "done", num: true, cell: e => (e.done != null ? `${num(e.done)} ${e.unit ?? ""}` : "") },
        { key: "m", head: "message", cell: e => e.message ?? "", title: e => e.message ?? "" },
      ]} />
      <Hint><Lbl>source</Lbl> last event of each job, from logs/jobs.jsonl (relic3 JobEvent) · {evs.length} jobs · read {log.at?.toLocaleTimeString() ?? "never"}</Hint>
    </>
  );
}
