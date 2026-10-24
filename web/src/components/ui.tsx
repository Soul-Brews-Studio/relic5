// Small building blocks shared by every view, in relic-scan's app vocabulary (relic4-scan src/page/dash.css): amber primary
// action, hairline borders, 16px cards, tracked uppercase stat labels, numbers in tabular figures. Each one owns its
// Tailwind classes, so a view only composes them.
import type { ReactNode } from "react";

const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");
export { cx };

/** A view's head: the title says what the view is (no eyebrow), one dim line under it, actions on the right. */
export function PageHead({ title, sub, children }: { title: ReactNode; sub?: ReactNode; children?: ReactNode }) {
  return (
    <header className="mb-8 flex flex-wrap items-end gap-x-8 gap-y-4">
      <div className="min-w-0 flex-1">
        <h1 className="m-0 text-xl lg:text-2xl font-extrabold tracking-[-0.02em] text-text text-balance">{title}</h1>
        {sub && <p className="m-0 mt-3 max-w-[75ch] text-base text-muted">{sub}</p>}
      </div>
      {children && <div className="flex flex-wrap items-center gap-3">{children}</div>}
    </header>
  );
}

/** The one container: a 16px card on the canvas. Never put a Card inside a Card. */
export function Card({ children, title, tone, className, pad = true }:
  { children: ReactNode; title?: ReactNode; tone?: "amber" | "cyan"; className?: string; pad?: boolean }) {
  return (
    <section className={cx("min-w-0 rounded-2xl border border-line bg-panel", pad && "p-6", className)}>
      {title && <h2 className={cx("m-0 mb-4 flex items-center gap-2.5 text-base font-bold", tone === "cyan" ? "text-accent" : tone === "amber" ? "text-amber" : "text-text")}>{title}</h2>}
      {children}
    </section>
  );
}

export function Lbl({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cx("text-xs font-bold tracking-[0.14em] text-muted uppercase", className)}>{children}</span>;
}

export function Btn({ children, primary, size, ...p }: { primary?: boolean; size?: "lg" } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button {...p} className={cx("inline-flex items-center justify-center gap-2 border font-semibold whitespace-nowrap",
      size === "lg" ? "min-h-14 rounded-xl px-7 text-base" : "min-h-11 rounded-lg px-4 text-sm",
      "transition-[background-color,border-color,color,filter] duration-[120ms] ease-[var(--ease-out)] disabled:cursor-not-allowed disabled:opacity-55",
      primary ? "border-transparent bg-accent text-on-accent hover:brightness-110 active:translate-y-px active:brightness-95" : "border-line bg-raised text-soft hover:border-line-strong hover:text-text",
      p.className)}>{children}</button>
  );
}

/** Segmented picker: one of `options`, pressed state on the chosen one. */
export function Seg<T extends string>({ value, options, onChange, label, block }:
  { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void; label: string; block?: boolean }) {
  return (
    <div role="group" aria-label={label} className={cx("gap-1 rounded-[10px] border border-line bg-deep p-1", block ? "grid grid-cols-3" : "inline-flex w-max")}>
      {options.map(o => (
        <button key={o.value} type="button" aria-pressed={value === o.value} onClick={() => onChange(o.value)}
          className={cx("min-h-9 rounded-[7px] px-3 text-xs font-semibold whitespace-nowrap transition-colors duration-[120ms]",
            value === o.value ? "bg-accent-wash text-text shadow-[inset_0_0_0_1px_var(--accent)]" : "text-muted hover:text-text")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export const inputCls = "h-11 min-w-0 rounded-lg border border-line bg-deep px-3 text-sm text-text placeholder:text-faint hover:border-line-strong focus:border-accent";

export type Tone = "ok" | "warn" | "bad" | "dim" | "live";
const tones: Record<Tone, string> = {
  live: "bg-accent-wash text-accent", ok: "bg-ok-wash text-ok", warn: "bg-warning-wash text-warning", bad: "bg-danger-wash text-danger", dim: "bg-raised text-muted",
};
export function Chip({ tone = "dim", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return <span title={title} className={cx("inline-flex items-baseline gap-1 rounded-md px-2 py-px text-xs font-semibold tracking-[0.02em]", tones[tone])}>{children}</span>;
}

/** One number with its label above and an optional detail line under it (relic-scan's .stat). */
export function Stat({ label, value, tone, note }: { label: string; value: ReactNode; tone?: Tone; note?: ReactNode }) {
  const color = tone === "live" ? "text-accent" : tone === "ok" ? "text-ok" : tone === "warn" ? "text-warning" : tone === "bad" ? "text-danger" : "text-text";
  return (
    <div className="min-w-0">
      <Lbl>{label}</Lbl>
      <div className={cx("mt-1.5 text-xl font-extrabold tracking-[-0.01em] tabular-nums", color)}>{value}</div>
      {note && <div className="mt-1 truncate text-xs text-muted">{note}</div>}
    </div>
  );
}
export function Stats({ children }: { children: ReactNode }) {
  return <div className="mb-8 grid grid-cols-[repeat(auto-fit,minmax(170px,1fr))] gap-x-8 gap-y-6">{children}</div>;
}

export function SectionHead({ children, sub }: { children: ReactNode; sub?: ReactNode }) {
  return (
    <div className="mt-12 mb-5">
      <h2 className="m-0 text-lg font-bold tracking-[-0.01em] text-text">{children}</h2>
      {sub && <p className="m-0 mt-1.5 max-w-[75ch] text-sm text-muted">{sub}</p>}
    </div>
  );
}
/** Where a list's numbers came from: the route, when, how long. Quiet, one line. */
export function Hint({ children }: { children: ReactNode }) {
  return <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-xs text-faint">{children}</div>;
}
export function State({ children, error }: { children: ReactNode; error?: boolean }) {
  return <div className={cx("rounded-xl px-5 py-6 text-sm", error ? "bg-danger-wash whitespace-pre-wrap text-danger" : "text-muted")}>{children}</div>;
}
export const Loading = ({ label = "Loading" }: { label?: string }) => <div role="progressbar" aria-label={label} className="loading-bar" />;

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="rounded-md border border-line bg-raised px-1.5 font-mono text-xs text-soft">{children}</kbd>;
}

/** Who said it: a dot and a word, cyan for the human, amber for the assistant, violet for tools. */
export function Who({ role }: { role: string }) {
  const c = role === "user" ? "text-user" : role === "assistant" ? "text-assistant" : "text-tool";
  const d = role === "user" ? "bg-user" : role === "assistant" ? "bg-assistant" : "bg-tool";
  return <span className={cx("inline-flex items-center gap-1.5 font-semibold", c)}><span className={cx("size-1.5 rounded-full", d)} />{role === "user" ? "human" : role}</span>;
}

/** Text with each query word wrapped in <mark>, without ever injecting HTML. */
export function Marked({ text, q }: { text: string; q: string }) {
  const words = q.split(/\s+/).filter(Boolean).map(w => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (!words.length) return <>{text}</>;
  const parts = text.split(new RegExp(`(${words.join("|")})`, "gi"));
  return <>{parts.map((p, i) => (i % 2 ? <mark key={i}>{p}</mark> : p))}</>;
}

/** The one "pick some of these" control: chips that press (machines, who). Pressed = cyan outline on a cyan wash, the
 *  same idiom as Seg and the sidebar's active item (Panel B: five ways of drawing "selected" became one). */
export function Toggle({ pressed, onClick, children, dot }: { pressed: boolean; onClick: () => void; children: ReactNode; dot?: string }) {
  return (
    <button type="button" aria-pressed={pressed} onClick={onClick}
      className={cx("inline-flex min-h-11 items-center gap-2 rounded-lg border px-3.5 text-sm font-semibold transition-colors duration-[120ms]",
        pressed ? "border-accent bg-accent-wash text-text" : "border-line text-muted hover:border-line-strong hover:text-text")}>
      {dot && <span className={cx("size-2 rounded-full", dot, !pressed && "opacity-40")} />}{children}
    </button>
  );
}

/** Machine picker (Search rail, Live head): "all" plus each machine. */
/** Which machine: the same segmented control as every other "pick one" (Search, Live). */
export function MachinePick({ machine, machines, onChange, counts }: { machine: string; machines: string[]; onChange: (m: string) => void; counts?: Record<string, number> }) {
  if (machines.length < 2) return null;
  return <Seg label="Machine" value={machine} onChange={onChange} options={["", ...machines].map(m => ({ value: m, label: `${m || "all machines"}${counts ? ` · ${counts[m] ?? 0}` : ""}` }))} />;
}
