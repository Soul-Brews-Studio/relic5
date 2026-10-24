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
export const Shield = (p: P) => <svg {...base(p)}><path d="M12 3l7 3v5.5c0 4.4-3 8-7 9.5-4-1.5-7-5.1-7-9.5V6l7-3z" /><path d="M9 12l2.2 2.2L15.5 10" /></svg>;
export const Disk = (p: P) => <svg {...base(p)}><ellipse cx="12" cy="6" rx="8" ry="3" /><path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" /></svg>;
export const Pulse = (p: P) => <svg {...base(p)}><path d="M3 12h4l2.5-6 5 12 2.5-6h4" /></svg>;
export const Arrow = (p: P) => <svg {...base(p)}><path d="M5 12h14M13 6l6 6-6 6" /></svg>;
export const Sun = (p: P) => <svg {...base(p)}><circle cx="12" cy="12" r="4" /><path d="M12 2.5v2M12 19.5v2M4.6 4.6l1.4 1.4M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4L6 18M18 6l1.4-1.4" /></svg>;
export const Moon = (p: P) => <svg {...base(p)}><path d="M20 14.5A8 8 0 019.5 4a8 8 0 1010.5 10.5z" /></svg>;
