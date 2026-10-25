// The Asked page's two charts (calls per hour with zero-hit searches, p50/p95 answer time), on Asked and on Home.
import { useState } from "react";
import { bkk, num } from "../format";
import type { AskedStats } from "../types";

// ---- charts: inline SVG, one axis each, thin marks, a readout line for hover ----------------------------------

export function HourBars({ s }: { s: AskedStats }) {
  const [hov, setHov] = useState(-1);
  const H = 120, max = Math.max(1, ...s.hours.map(h => h.n)), n = s.hours.length || 1;
  const h = s.hours[hov];
  return (
    <figure className="m-0 min-w-0">
      <figcaption className="mb-2 flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm">
        <span className="font-bold text-text">Calls per hour</span>
        <span className="inline-flex items-center gap-1.5 text-muted"><i className="inline-block size-2.5 rounded-sm bg-accent" />answered</span>
        <span className="inline-flex items-center gap-1.5 text-muted"><i className="inline-block size-2.5 rounded-sm bg-amber" />search with zero hits</span>
        <span className="ml-auto font-mono text-xs text-muted tabular-nums" aria-live="polite">
          {h ? `${bkk(h.hour + ":00:00Z")} · ${h.n} calls · ${h.searches} searches · ${h.zero} zero` : `peak ${max} an hour`}</span>
      </figcaption>
      <svg viewBox={`0 0 ${n * 10} ${H}`} preserveAspectRatio="none" className="block h-[120px] w-full" role="img"
        aria-label={`Calls per hour over ${s.window_h} hours, peak ${max}`} onMouseLeave={() => setHov(-1)}>
        <line x1="0" x2={n * 10} y1={H - 0.5} y2={H - 0.5} stroke="var(--line-strong)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
        {s.hours.map((x, i) => {
          const all = (x.n / max) * (H - 4), z = (x.zero / max) * (H - 4);
          return (
            <g key={x.hour} onMouseEnter={() => setHov(i)}>
              <rect x={i * 10} y="0" width="10" height={H} fill="transparent" />
              <rect x={i * 10 + 1.5} y={H - all} width="7" height={Math.max(0, all - z - (z ? 0.6 : 0))} rx="1" fill="var(--accent)" opacity={hov === -1 || hov === i ? 1 : 0.45} />
              {z > 0 && <rect x={i * 10 + 1.5} y={H - z} width="7" height={z} fill="var(--amber)" opacity={hov === -1 || hov === i ? 1 : 0.45} />}
            </g>
          );
        })}
      </svg>
      <div className="mt-1 flex justify-between font-mono text-xs text-faint"><span>{s.hours[0] ? bkk(s.hours[0].hour + ":00:00Z") : ""}</span><span>now</span></div>
    </figure>
  );
}

export function Latency({ s }: { s: AskedStats }) {
  const [hov, setHov] = useState(-1);
  const H = 120, pts = s.hours, max = Math.max(1, ...pts.map(h => h.p95_ms ?? 0)), n = pts.length || 1;
  const y = (v: number | null) => (v == null ? null : H - 4 - (v / max) * (H - 10));
  const line = (k: "p50_ms" | "p95_ms") => pts.map((h, i) => { const v = y(h[k]); return v == null ? "" : `${i * 10 + 5},${v}`; }).filter(Boolean).join(" ");
  const h = pts[hov];
  return (
    <figure className="m-0 min-w-0">
      <figcaption className="mb-2 flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm">
        <span className="font-bold text-text">Answer time</span>
        <span className="inline-flex items-center gap-1.5 text-muted"><i className="inline-block h-0.5 w-3 bg-accent" />p50</span>
        <span className="inline-flex items-center gap-1.5 text-muted"><i className="inline-block h-0.5 w-3 bg-amber" />p95</span>
        <span className="ml-auto font-mono text-xs text-muted tabular-nums" aria-live="polite">
          {h ? `${bkk(h.hour + ":00:00Z")} · p50 ${h.p50_ms ?? "–"} ms · p95 ${h.p95_ms ?? "–"} ms` : `top of scale ${num(max)} ms`}</span>
      </figcaption>
      <svg viewBox={`0 0 ${n * 10} ${H}`} preserveAspectRatio="none" className="block h-[120px] w-full" role="img"
        aria-label={`p50 and p95 answer time per hour, highest p95 ${max} ms`} onMouseLeave={() => setHov(-1)}>
        <line x1="0" x2={n * 10} y1={H - 0.5} y2={H - 0.5} stroke="var(--line-strong)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
        {hov >= 0 && <line x1={hov * 10 + 5} x2={hov * 10 + 5} y1="0" y2={H} stroke="var(--line-strong)" vectorEffect="non-scaling-stroke" />}
        <polyline points={line("p95_ms")} fill="none" stroke="var(--amber)" strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
        <polyline points={line("p50_ms")} fill="none" stroke="var(--accent)" strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
        {pts.map((x, i) => <rect key={x.hour} x={i * 10} y="0" width="10" height={H} fill="transparent" onMouseEnter={() => setHov(i)} />)}
      </svg>
      <div className="mt-1 flex justify-between font-mono text-xs text-faint"><span>{pts[0] ? bkk(pts[0].hour + ":00:00Z") : ""}</span><span>now</span></div>
    </figure>
  );
}

