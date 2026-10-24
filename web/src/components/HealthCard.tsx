import type { ReactNode } from "react";
import { cx } from "./ui";

export type Level = "ok" | "warning" | "failed" | "unknown";

const ring: Record<Level, string> = {
  ok: "bg-accent-wash text-accent", warning: "bg-[color-mix(in_srgb,var(--warning)_14%,transparent)] text-warning",
  failed: "bg-danger-wash text-danger", unknown: "bg-raised text-muted",
};
const word: Record<Level, string> = { ok: "OK", warning: "WARNING", failed: "FAILED", unknown: "UNKNOWN" };
const mark: Record<Level, string> = { ok: "✓", warning: "!", failed: "✕", unknown: "?" };

/** A big round badge: ✓ ! ✕ ? on the level's colour (Relic Scanner's Health page). */
export function Badge({ level, size = "md" }: { level: Level; size?: "md" | "lg" }) {
  return (
    <span className={cx("grid flex-none place-items-center rounded-full font-sans font-bold", ring[level],
      size === "lg" ? "size-16 text-2xl" : "size-11 text-lg")}>{mark[level]}</span>
  );
}

/** One plain-language check: what, its level, one sentence, and the command that would fix or show it. */
export function HealthCard({ title, level, children, command, big }: {
  title: string; level: Level; children: ReactNode; command?: string; big?: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-line bg-panel p-5">
      <div className="flex items-center gap-3.5">
        <Badge level={level} />
        <div className="min-w-0">
          <div className="truncate font-sans text-[15px] font-semibold text-text">{title}</div>
          <div className={cx("text-[10px] font-bold tracking-[.14em]", level === "ok" ? "text-accent" : level === "failed" ? "text-danger" : level === "warning" ? "text-warning" : "text-muted")}>{word[level]}</div>
        </div>
        {big != null && <div className="ml-auto font-sans text-2xl font-bold tabular-nums text-text">{big}</div>}
      </div>
      <p className="m-0 font-sans text-[13px] leading-relaxed text-soft">{children}</p>
      {command && (
        <code className="mt-auto flex items-center gap-2 rounded-lg bg-deep px-3 py-2 text-[11px] text-soft">
          <span className="text-faint">$</span><span className="truncate">{command}</span>
        </code>
      )}
    </div>
  );
}
