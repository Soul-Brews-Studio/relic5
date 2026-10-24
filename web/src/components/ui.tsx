// Small building blocks shared by every view. Each one owns its Tailwind classes, so a view only composes them.
import type { ReactNode } from "react";

const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");
export { cx };

export function Lbl({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cx("text-[9px] font-semibold uppercase tracking-[.12em] text-muted", className)}>{children}</span>;
}

export function Btn({ children, primary, ...p }: { primary?: boolean } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button {...p} className={cx("min-h-9 whitespace-nowrap rounded-[5px] border px-3.5 text-[11px] font-semibold disabled:cursor-not-allowed disabled:opacity-55",
      primary ? "border-accent-dim bg-accent-dim text-accent-ink hover:brightness-110" : "border-line bg-raised text-soft hover:border-line-strong hover:text-text",
      p.className)}>{children}</button>
  );
}

/** Segmented picker: one of `options`, pressed state on the chosen one. */
export function Seg<T extends string>({ value, options, onChange, label }:
  { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void; label: string }) {
  return (
    <div role="group" aria-label={label} className="inline-flex w-max rounded-[5px] bg-raised">
      {options.map((o, i) => (
        <button key={o.value} type="button" aria-pressed={value === o.value} onClick={() => onChange(o.value)}
          className={cx("min-h-9 whitespace-nowrap border border-line px-3 text-[11px] font-semibold",
            i === 0 && "rounded-l-[5px]", i === options.length - 1 ? "rounded-r-[5px]" : "border-r-0",
            value === o.value ? "border-line-strong bg-accent-dim text-accent-ink" : "bg-transparent text-muted hover:text-text")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Field({ label, children, wide, htmlFor }: { label: string; children: ReactNode; wide?: boolean; htmlFor?: string }) {
  return (
    <div className={cx("flex min-w-0 flex-col gap-1.5", wide ? "flex-[1_1_300px]" : "flex-[0_1_190px]")}>
      <label htmlFor={htmlFor}><Lbl>{label}</Lbl></label>
      {children}
    </div>
  );
}

export const inputCls = "h-9 min-w-0 rounded-[5px] border border-line bg-deep px-3 text-xs text-text placeholder:text-faint hover:border-line-strong";

export function Toolbar({ children, onSubmit }: { children: ReactNode; onSubmit?: () => void }) {
  return (
    <form onSubmit={e => { e.preventDefault(); onSubmit?.(); }}
      className="flex flex-wrap items-end gap-x-3.5 gap-y-3 border-b border-line bg-panel px-4 pt-3.5 pb-3">{children}</form>
  );
}

export type Tone = "ok" | "warn" | "bad" | "dim";
const tones: Record<Tone, string> = {
  ok: "border-accent-dim text-accent", warn: "border-warning text-warning", bad: "border-danger text-danger", dim: "border-line text-muted",
};
export function Chip({ tone = "dim", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return <span title={title} className={cx("inline-flex items-baseline gap-1 rounded border px-1.5 text-[10px] font-semibold", tones[tone])}>{children}</span>;
}

export function Stat({ label, value, tone, note }: { label: string; value: ReactNode; tone?: Tone; note?: string }) {
  const color = tone === "ok" ? "text-accent" : tone === "warn" ? "text-warning" : tone === "bad" ? "text-danger" : "text-text";
  return (
    <div className="border-r border-line px-4 py-3 last:border-r-0">
      <Lbl className="mb-1 block">{label}</Lbl>
      <b className={cx("text-base tabular-nums", color)}>{value}</b>
      {note && <div className="truncate text-[10px] text-faint">{note}</div>}
    </div>
  );
}
export function Stats({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-[repeat(auto-fit,minmax(160px,1fr))] border-b border-line">{children}</div>;
}

export function SectionHead({ children }: { children: ReactNode }) {
  return <div className="px-4 pt-3.5 pb-1.5"><Lbl>{children}</Lbl></div>;
}
export function Hint({ children }: { children: ReactNode }) {
  return <div className="border-b border-line bg-panel px-4 py-2 text-[11px] text-muted">{children}</div>;
}
export function State({ children, error }: { children: ReactNode; error?: boolean }) {
  return <div className={cx("px-4 py-6 text-xs", error ? "border-l-2 border-danger bg-danger-wash whitespace-pre-wrap text-danger" : "text-faint")}>{children}</div>;
}
export const Loading = () => <div className="loading-bar" />;

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="rounded border border-line bg-raised px-1 text-[10px] text-soft">{children}</kbd>;
}

/** Who said it, coloured the way Structor colours roles. */
export function Who({ role }: { role: string }) {
  const c = role === "user" ? "text-user" : role === "assistant" ? "text-assistant" : "text-tool";
  return <span className={cx("font-semibold", c)}>{role}</span>;
}

/** Text with each query word wrapped in <mark>, without ever injecting HTML. */
export function Marked({ text, q }: { text: string; q: string }) {
  const words = q.split(/\s+/).filter(Boolean).map(w => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (!words.length) return <>{text}</>;
  const parts = text.split(new RegExp(`(${words.join("|")})`, "gi"));
  return <>{parts.map((p, i) => (i % 2 ? <mark key={i}>{p}</mark> : p))}</>;
}
