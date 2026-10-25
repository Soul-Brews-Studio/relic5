// One small icon set, drawn for the hub: 24-unit grid, 1.75 stroke, round caps. No emoji, no glyphs.
import type { SVGProps } from "react";

type P = SVGProps<SVGSVGElement> & { size?: number };
const base = ({ size = 20, ...p }: P) => ({
  width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.75,
  strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true, ...p,
});

export const Check = (p: P) => <svg {...base(p)}><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>;
export const Alert = (p: P) => <svg {...base(p)}><path d="M12 8v5" /><path d="M12 16.5v.01" /><path d="M10.3 3.9L2.6 17.4A2 2 0 004.3 20.4h15.4a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z" /></svg>;
export const Cross = (p: P) => <svg {...base(p)}><path d="M6.5 6.5l11 11M17.5 6.5l-11 11" /></svg>;
export const Question = (p: P) => <svg {...base(p)}><path d="M9.2 9.3a3 3 0 015.6 1.2c0 2-2.8 2.5-2.8 4.2" /><path d="M12 18v.01" /></svg>;
export const Machine = (p: P) => <svg {...base(p)}><rect x="3" y="4" width="18" height="12" rx="2" /><path d="M8 20h8M12 16v4" /></svg>;
export const Search = (p: P) => <svg {...base(p)}><circle cx="11" cy="11" r="6.5" /><path d="M20 20l-4.2-4.2" /></svg>;
export const Vector = (p: P) => <svg {...base(p)}><circle cx="6" cy="17" r="2.2" /><circle cx="18" cy="6" r="2.2" /><circle cx="17" cy="17" r="2.2" /><path d="M7.8 15.6l8.4-8.2M8.2 17h6.6" /></svg>;
export const Lock = (p: P) => <svg {...base(p)}><rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3" /></svg>;
export const Shield = (p: P) => <svg {...base(p)}><path d="M12 3l7 3v5.5c0 4.4-3 8-7 9.5-4-1.5-7-5.1-7-9.5V6l7-3z" /><path d="M9 12l2.2 2.2L15.5 10" /></svg>;
export const Disk = (p: P) => <svg {...base(p)}><ellipse cx="12" cy="6" rx="8" ry="3" /><path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" /></svg>;
export const Pulse = (p: P) => <svg {...base(p)}><path d="M3 12h4l2.5-6 5 12 2.5-6h4" /></svg>;
export const Chevron = (p: P) => <svg {...base(p)}><path d="M9 6l6 6-6 6" /></svg>;
export const Arrow = (p: P) => <svg {...base(p)}><path d="M5 12h14M13 6l6 6-6 6" /></svg>;
export const Sun = (p: P) => <svg {...base(p)}><circle cx="12" cy="12" r="4" /><path d="M12 2.5v2M12 19.5v2M4.6 4.6l1.4 1.4M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4L6 18M18 6l1.4-1.4" /></svg>;
export const Moon = (p: P) => <svg {...base(p)}><path d="M20 14.5A8 8 0 019.5 4a8 8 0 1010.5 10.5z" /></svg>;
export const Home = (p: P) => <svg {...base(p)}><path d="M4 10.5L12 4l8 6.5V19a1 1 0 01-1 1h-4.5v-5.5h-5V20H5a1 1 0 01-1-1v-8.5z" /></svg>;
export const Live = (p: P) => <svg {...base(p)}><circle cx="12" cy="12" r="2.2" /><path d="M7.8 7.8a6 6 0 000 8.4M16.2 7.8a6 6 0 010 8.4M5 5a10 10 0 000 14M19 5a10 10 0 010 14" /></svg>;
export const Note = (p: P) => <svg {...base(p)}><path d="M7 3.5h7.5L19 8v12a.5.5 0 01-.5.5h-11.5A1 1 0 016 19.5v-15a1 1 0 011-1z" /><path d="M14 3.5V8h5M9.5 12.5h5M9.5 16h5" /></svg>;
export const Plug = (p: P) => <svg {...base(p)}><path d="M9 3v4.5M15 3v4.5M6.5 7.5h11V11a5.5 5.5 0 01-11 0V7.5zM12 16.5V21" /></svg>;
export const Jobs = (p: P) => <svg {...base(p)}><path d="M9 6.5h11M9 12h11M9 17.5h11" /><path d="M4 6.5l1 1 2-2M4 12l1 1 2-2M4 17.5l1 1 2-2" /></svg>;
export const Asked = (p: P) => <svg {...base(p)}><path d="M5 5.5h14a1 1 0 011 1v9a1 1 0 01-1 1h-7.5L7 20v-3.5H5a1 1 0 01-1-1v-9a1 1 0 011-1z" /><path d="M9.8 9.4a2.2 2.2 0 014.2.8c0 1.4-2 1.6-2 2.8M12 14.6v.01" /></svg>;
export const Rows = (p: P) => <svg {...base(p)}><rect x="3.5" y="4.5" width="17" height="5" rx="1.5" /><rect x="3.5" y="11.5" width="17" height="8" rx="1.5" /></svg>;
export const Menu = (p: P) => <svg {...base(p)}><path d="M4 7h16M4 12h16M4 17h16" /></svg>;
export const Globe = (p: P) => <svg {...base(p)}><circle cx="12" cy="12" r="8.5" /><ellipse cx="12" cy="12" rx="3.6" ry="8.5" /><path d="M3.5 12h17" /></svg>;
export const Psi = (p: P) => <svg {...base(p)}><path d="M12 4v16M6 6.5v3a6 6 0 0012 0v-3M9 20h6" /></svg>;
export const Tree = (p: P) => <svg {...base(p)}><circle cx="6" cy="6" r="2.2" /><circle cx="18" cy="12" r="2.2" /><circle cx="18" cy="19" r="2.2" /><path d="M6 8.2V16a3 3 0 003 3h6.8M6 12h9.8" /></svg>;
export const Columns = (p: P) => <svg {...base(p)}><rect x="3.5" y="4.5" width="7" height="15" rx="1.5" /><rect x="13.5" y="4.5" width="7" height="15" rx="1.5" /><path d="M6 9h2M16 9h2M6 12.5h2M16 12.5h2" /></svg>;
export const Filter = (p: P) => <svg {...base(p)}><path d="M4 5.5h16l-6.2 7.3V19l-3.6-1.8v-4.4L4 5.5z" /></svg>;
export const Session = (p: P) => <svg {...base(p)}><path d="M4.5 6.5a2 2 0 012-2h11a2 2 0 012 2v8a2 2 0 01-2 2H11l-4.5 3.5v-3.5h0a2 2 0 01-2-2v-8z" /><path d="M8.5 9.5h7M8.5 12.5h4.5" /></svg>;
export const Gear = (p: P) => <svg {...base(p)}><circle cx="12" cy="12" r="3" /><path d="M12 2.5v2.2M12 19.3v2.2M4.6 4.6l1.6 1.6M17.8 17.8l1.6 1.6M2.5 12h2.2M19.3 12h2.2M4.6 19.4l1.6-1.6M17.8 6.2l1.6-1.6" /></svg>;
export const Close = (p: P) => <svg {...base(p)}><path d="M7 7l10 10M17 7L7 17" /></svg>;

/** The hub's mark: a serif Psi on a circle in relic5's blue (relic-scan keeps the amber one) (ARRA Oracle Unconference #1 logo), with a small 5. SVG text in a
 *  serif stack, so it needs no font file. */
export function Mark({ size = 40 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" aria-hidden="true">
      <circle cx="20" cy="20" r="18" fill="var(--accent)" />
      <text x="19" y="27.5" textAnchor="middle" fontSize="22" fontFamily="'Instrument Serif', Georgia, 'Times New Roman', serif" fill="var(--on-accent)">Ψ</text>
      <text x="29.5" y="31" textAnchor="middle" fontSize="9" fontWeight="700" fontFamily="-apple-system, system-ui, sans-serif" fill="var(--on-accent)">5</text>
    </svg>
  );
}
export const More = (p: P) => <svg {...base(p)}><circle cx="5.5" cy="12" r="1.3" /><circle cx="12" cy="12" r="1.3" /><circle cx="18.5" cy="12" r="1.3" /></svg>;
