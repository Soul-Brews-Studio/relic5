import { useEffect, useState, type ReactNode } from "react";

/** A progress ring with a big number in the middle (Relic Scanner's Smart Scan and Embedding pages). It fills once
 *  from empty when the page opens: the page's one authored motion. `frac` null = unknown: drawn empty, never 0%. */
export function Ring({ frac, value, of, label, color = "var(--accent)" }:
  { frac: number | null; value: ReactNode; of?: ReactNode; label: string; color?: string }) {
  const r = 70, c = 2 * Math.PI * r, f = frac == null ? 0 : Math.max(0, Math.min(1, frac));
  const [shown, setShown] = useState(0);
  useEffect(() => { const t = requestAnimationFrame(() => setShown(f)); return () => cancelAnimationFrame(t); }, [f]);
  return (
    <div className="relative grid size-40 flex-none place-items-center sm:size-56 lg:size-64">
      <svg viewBox="0 0 160 160" className="absolute inset-0 -rotate-90" role="img" aria-label={`${label}: ${frac == null ? "unknown" : Math.round(f * 100) + "%"}`}>
        <circle cx="80" cy="80" r={r} fill="none" stroke="var(--raised)" strokeWidth="11" />
        <circle cx="80" cy="80" r={r} fill="none" stroke={color} strokeWidth="11" strokeLinecap="round"
          strokeDasharray={`${c * shown} ${c}`} style={{ transition: "stroke-dasharray 1.4s cubic-bezier(.16,1,.3,1)" }} className="motion-reduce:transition-none" />
      </svg>
      <div className="relative flex flex-col items-center px-4 text-center sm:px-8">
        <b className="font-sans text-[17px] leading-tight sm:text-[26px] font-bold tabular-nums text-text">{value}</b>
        {of && <span className="mt-0.5 font-sans text-[10px] sm:text-[12px] leading-tight font-semibold" style={{ color }}>{of}</span>}
        <span className="mt-1.5 font-sans text-[12px] font-semibold text-muted">{label}</span>
      </div>
    </div>
  );
}
