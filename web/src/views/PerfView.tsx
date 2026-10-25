// Every request the hub answered, timed (perf.py; Nat, 2026-10-25: "performance log and page to display each like
// request?"): per route p50/p95/max, the slowest and the newest requests, the hub's memory and the machine's load.
import { useState } from "react";
import { usePoll } from "../api";
import { DataTable } from "../components/DataTable";
import { Chip, Hint, PageHead, SectionHead, Stat, Stats, cx } from "../components/ui";
import { bytes, num, recent } from "../format";

interface Req { at: string; method: string; path: string; route: string; status: number; ms: number; bytes: number | null; door: string | null; q: string }
interface Route { route: string; count: number; p50: number | null; p95: number | null; max: number; errors: number; slow: number; bytes: number }
interface Sample { at: string; rss_mb: number; load: number; per_min: number }
interface Perf { minutes: number; requests: number; routes: Route[]; slowest: Req[]; recent: Req[]; samples: Sample[]; rss_mb: number; load: number[]; cpus: number }

const ms = (v: number | null | undefined) => (v == null ? "—" : v >= 1000 ? `${(v / 1000).toFixed(v >= 10000 ? 0 : 1)} s` : `${Math.round(v)} ms`);
const tone = (v: number | null | undefined) => (v == null ? "text-muted" : v >= 3000 ? "text-danger" : v >= 800 ? "text-warning" : "text-text");

/** A line of the last few hours: one thin stroke, its newest value at the end. */
function Spark({ xs, label, fmt }: { xs: number[]; label: string; fmt: (v: number) => string }) {
  if (xs.length < 2) return null;
  const w = 220, h = 36, lo = Math.min(...xs), hi = Math.max(...xs), span = hi - lo || 1;
  const pts = xs.map((v, i) => `${(i / (xs.length - 1)) * w},${h - 3 - ((v - lo) / span) * (h - 6)}`).join(" ");
  return (
    <figure className="m-0 min-w-0" aria-label={`${label}: ${fmt(xs[xs.length - 1])} now, ${fmt(lo)} to ${fmt(hi)}`}>
      <figcaption className="text-xs text-muted">{label} · <b className="text-soft tabular-nums">{fmt(xs[xs.length - 1])}</b> <span className="text-faint">({fmt(lo)}–{fmt(hi)})</span></figcaption>
      <svg viewBox={`0 0 ${w} ${h}`} className="mt-1 h-9 w-full" preserveAspectRatio="none"><polyline points={pts} fill="none" stroke="var(--color-accent)" strokeWidth="2" vectorEffect="non-scaling-stroke" /></svg>
    </figure>
  );
}

export function PerfView({ on }: { on: boolean }) {
  const [minutes, setMinutes] = useState(60);
  const [route, setRoute] = useState("");
  const p = usePoll<Perf>(`/api/perf?minutes=${minutes}${route ? `&route=${encodeURIComponent(route)}` : ""}`, 10000, on);
  const d = p.data;
  const reqCols = [
    { key: "at", head: "when", w: "w-28", cell: (r: Req) => <time dateTime={r.at} title={r.at} className="tabular-nums">{recent(r.at)}</time> },
    { key: "ms", head: "time", num: true, w: "w-20", cell: (r: Req) => <b className={cx("tabular-nums", tone(r.ms))}>{ms(r.ms)}</b> },
    { key: "st", head: "status", w: "w-16", cell: (r: Req) => <Chip tone={r.status >= 500 ? "bad" : r.status >= 400 ? "warn" : "dim"}>{r.status}</Chip> },
    { key: "p", head: "request", lead: true, cell: (r: Req) => <span className="font-mono text-xs break-all text-soft">{r.method !== "GET" ? r.method + " " : ""}{r.path}{r.q ? "?" + r.q : ""}</span>, title: (r: Req) => `${r.path}?${r.q}` },
    { key: "b", head: "size", num: true, w: "w-20", cell: (r: Req) => (r.bytes ? bytes(r.bytes) : "") },
    { key: "d", head: "door", w: "w-28", cell: (r: Req) => <span className="text-xs text-muted">{r.door}</span> },
  ];
  return (
    <>
      <PageHead title="Performance" sub="Every request this hub answered, timed on the hub itself (the network to your browser is not counted). Kept in memory for the last 5,000 requests and written to logs/requests/ every 30 s.">
        <div role="radiogroup" className="inline-flex rounded-xl border border-line bg-deep p-1">
          {[15, 60, 360, 1440].map(m => (
            <button key={m} type="button" role="radio" aria-checked={minutes === m} onClick={() => setMinutes(m)}
              className={cx("min-h-9 rounded-lg px-3 text-sm font-semibold", minutes === m ? "bg-raised text-text" : "text-muted hover:text-text")}>{m < 60 ? `${m} min` : `${m / 60} h`}</button>
          ))}
        </div>
      </PageHead>
      {p.error && <p className="m-0 mb-6 text-sm text-danger">{p.error}</p>}
      {d && <>
        <Stats>
          <Stat label="requests" value={num(d.requests)} note={`in the last ${minutes < 60 ? minutes + " min" : minutes / 60 + " h"}`} />
          <Stat label="slow (≥ 1 s)" value={num(d.routes.reduce((a, r) => a + r.slow, 0))} tone={d.routes.some(r => r.slow) ? "warn" : "ok"} />
          <Stat label="errors (5xx)" value={num(d.routes.reduce((a, r) => a + r.errors, 0))} tone={d.routes.some(r => r.errors) ? "bad" : "ok"} />
          <Stat label="hub memory" value={`${(d.rss_mb / 1024).toFixed(1)} GB`} />
          <Stat label="machine load" value={d.load[0].toFixed(1)} tone={d.load[0] > d.cpus ? "bad" : d.load[0] > d.cpus / 2 ? "warn" : "ok"} note={`${d.cpus} cpus · 5 min ${d.load[1]} · 15 min ${d.load[2]}`} />
        </Stats>
        <div className="mb-2 grid gap-6 sm:grid-cols-3">
          <Spark xs={d.samples.map(s => s.rss_mb / 1024)} label="memory" fmt={v => `${v.toFixed(1)} GB`} />
          <Spark xs={d.samples.map(s => s.load)} label="load" fmt={v => v.toFixed(1)} />
          <Spark xs={d.samples.map(s => s.per_min)} label="requests a minute" fmt={v => String(Math.round(v))} />
        </div>
        <SectionHead sub="the routes that cost the most time first (p95 × count); pick one to see only its requests below">By route</SectionHead>
        <DataTable rows={d.routes} rowKey={r => r.route} active={d.routes.findIndex(r => r.route === route)} onRow={r => setRoute(route === r.route ? "" : r.route)} cols={[
          { key: "r", head: "route", lead: true, cell: r => <span className="font-mono text-xs text-text">{r.route}</span> },
          { key: "c", head: "count", num: true, w: "w-20", cell: r => num(r.count) },
          { key: "50", head: "p50", num: true, w: "w-20", cell: r => <span className={tone(r.p50)}>{ms(r.p50)}</span> },
          { key: "95", head: "p95", num: true, w: "w-20", cell: r => <b className={tone(r.p95)}>{ms(r.p95)}</b> },
          { key: "mx", head: "max", num: true, w: "w-20", cell: r => <span className={tone(r.max)}>{ms(r.max)}</span> },
          { key: "s", head: "slow", num: true, w: "w-16", cell: r => (r.slow ? <span className="text-warning">{r.slow}</span> : "") },
          { key: "e", head: "5xx", num: true, w: "w-16", cell: r => (r.errors ? <span className="text-danger">{r.errors}</span> : "") },
        ]} />
        <SectionHead sub={route ? <>only <code className="font-mono">{route}</code> · <button type="button" className="font-semibold text-accent" onClick={() => setRoute("")}>show every route</button></> : "the 50 slowest in the window"}>Slowest</SectionHead>
        <DataTable rows={d.slowest} rowKey={(r, i) => r.at + i} cols={reqCols} empty="No requests in the window." />
        <SectionHead sub="newest first, the last 200">Each request</SectionHead>
        <DataTable rows={d.recent} rowKey={(r, i) => r.at + i} cols={reqCols} empty="No requests in the window." />
        <Hint>GET /api/perf · read {p.at ? recent(p.at.toISOString()) : "…"} · every 10 s</Hint>
      </>}
    </>
  );
}
