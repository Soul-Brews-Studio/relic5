import type { ReactNode } from "react";

/** A progress ring with a big number in the middle (Relic Scanner's Smart Scan and Embedding pages).
 *  `frac` null = unknown: the ring is drawn empty and the label says so, never a made-up 0%. */
export function Ring({ frac, value, of, label, color = "var(--accent)" }:
  { frac: number | null; value: ReactNode; of?: ReactNode; label: string; color?: string }) {
  const r = 70, c = 2 * Math.PI * r, f = frac == null ? 0 : Math.max(0, Math.min(1, frac));
  return (
    <div className="relative grid size-64 flex-none place-items-center">
      <svg viewBox="0 0 160 160" className="absolute inset-0 -rotate-90">
        <circle cx="80" cy="80" r={r} fill="none" stroke="var(--raised)" strokeWidth="12" />
        <circle cx="80" cy="80" r={r} fill="none" stroke={color} strokeWidth="12" strokeLinecap="round"
          strokeDasharray={`${c * f} ${c}`} style={{ transition: "stroke-dasharray .6s ease" }} />
      </svg>
      <div className="relative flex flex-col items-center text-center">
        <b className="font-sans text-[26px] font-bold tabular-nums text-text">{value}</b>
        {of && <span className="max-w-44 font-sans text-[12px] font-semibold leading-tight" style={{ color }}>{of}</span>}
        <span className="mt-1 text-[9px] font-bold tracking-[.16em] text-muted uppercase">{label}</span>
      </div>
    </div>
  );
}
