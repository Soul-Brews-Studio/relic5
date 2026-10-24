import type { ReactNode } from "react";
import type { Status } from "../types";
import { num, secs } from "../format";
import { cx } from "./ui";

function Item({ label, children, warn }: { label: string; children: ReactNode; warn?: boolean }) {
  return (
    <span className="flex min-w-0 flex-wrap items-baseline gap-1.5 text-[11px] text-muted">
      {label} <b className={cx("text-xs font-semibold", warn ? "text-warning" : "text-soft")}>{children}</b>
    </span>
  );
}

/** The strip over the tabs: is search current, is anything running, what does the hub warn about. */
export function StatusBar({ s, error }: { s: Status | null; error: string | null }) {
  if (!s) return <div className="border-b border-line bg-panel px-4 py-3 text-[11px] text-muted">{error ?? "reading /api/status…"}</div>;
  const age = s.freshness.fts?.age_s, pending = s.watermarks.vectors.pending;
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2.5 border-b border-line bg-panel px-4 py-3">
      <Item label="BM25 index" warn={age != null && age > 3600}>{age == null ? "none" : `${secs(age)} old`}</Item>
      <Item label="vectors pending" warn={!!pending}>{num(pending)}</Item>
      <Item label="running" warn={s.jobs.running.length > 0}>{s.jobs.running.map(j => j.verb).join(", ") || "nothing"}</Item>
      <Item label="rows">{num(s.rows.text)} text · {num(s.rows.tools)} tools · {num(s.rows.thinking)} thinking</Item>
      <Item label="warnings" warn={s.warnings.length > 0}>{s.warnings.length || "none"}</Item>
      {error && <p className="m-0 basis-full rounded border-l-2 border-danger bg-danger-wash px-2 py-1.5 text-[11px] text-danger">last poll failed: {error}</p>}
      {s.warnings.map(w => <p key={w} className="m-0 basis-full rounded border-l-2 border-warning bg-raised px-2 py-1.5 text-[11px] text-soft">{w}</p>)}
    </div>
  );
}
