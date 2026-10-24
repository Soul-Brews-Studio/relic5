import type { ComponentType, ReactNode } from "react";
import { Alert, Check, Cross, Question } from "./Icons";
import { cx } from "./ui";

export type Level = "ok" | "warning" | "failed" | "unknown";

const tone: Record<Level, { ring: string; text: string; word: string; Icon: ComponentType<{ size?: number }> }> = {
  ok: { ring: "bg-accent-wash text-accent", text: "text-accent", word: "OK", Icon: Check },
  warning: { ring: "bg-[color-mix(in_srgb,var(--warning)_16%,transparent)] text-warning", text: "text-warning", word: "Needs a look", Icon: Alert },
  failed: { ring: "bg-danger-wash text-danger", text: "text-danger", word: "Failing", Icon: Cross },
  unknown: { ring: "bg-raised text-muted", text: "text-muted", word: "Unknown", Icon: Question },
};
export const levelText = (l: Level) => tone[l].text;
export const levelWord = (l: Level) => tone[l].word;

/** A round status badge with a drawn icon (Relic Scanner's Health page). */
export function Badge({ level, size = "md" }: { level: Level; size?: "md" | "lg" }) {
  const { ring, Icon } = tone[level];
  return (
    <span className={cx("grid flex-none place-items-center rounded-full", ring, size === "lg" ? "size-16" : "size-11")}>
      <Icon size={size === "lg" ? 30 : 20} />
    </span>
  );
}

/** One plain-language check: what, its level, the one number, one sentence, and the fix command when not OK.
 *  A failing card is drawn louder than an OK one: tinted ground and a strong outline, never the same quiet card. */
export function HealthCard({ title, level, children, command, big, icon: I }: {
  title: string; level: Level; children: ReactNode; command?: string; big?: ReactNode; icon?: ComponentType<{ size?: number }>;
}) {
  const loud = level === "failed" || level === "warning";
  return (
    <div className={cx("flex flex-col gap-3 rounded-2xl border p-5",
      level === "failed" ? "border-danger bg-danger-wash" : level === "warning" ? "border-warning bg-[color-mix(in_srgb,var(--warning)_7%,var(--panel))]" : "border-line bg-panel")}>
      <div className="flex items-center gap-3.5">
        <Badge level={level} />
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 truncate font-sans text-[15px] font-semibold text-text">{I && <span className="text-muted"><I size={16} /></span>}{title}</div>
          <div className={cx("font-sans text-[12px] font-semibold", tone[level].text)}>{tone[level].word}</div>
        </div>
        {big != null && <div className={cx("ml-auto font-sans text-2xl font-bold tabular-nums", loud ? tone[level].text : "text-text")}>{big}</div>}
      </div>
      <p className="m-0 font-sans text-[13px] leading-relaxed text-soft">{children}</p>
      {command && (
        <code className="mt-auto flex items-center gap-2 rounded-lg bg-deep px-3 py-2 text-[11px] text-soft">
          <span className="text-faint">$</span><span className="truncate select-all">{command}</span>
        </code>
      )}
    </div>
  );
}
