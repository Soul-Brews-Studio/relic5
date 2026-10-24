import type { ReactNode } from "react";
import { cx, State } from "./ui";

export interface Col<T> {
  key: string; head: string; cell: (row: T) => ReactNode; num?: boolean; title?: (row: T) => string;
}

/** One table for every list in the hub: sticky header, numeric columns right-aligned, rows optionally clickable.
 *  `flash` marks rows new since the last render (the Live view), `active` the row the keyboard is on. */
export function DataTable<T>({ cols, rows, rowKey, onRow, empty = "nothing yet", flash, active }: {
  cols: Col<T>[]; rows: T[]; rowKey: (row: T, i: number) => string; onRow?: (row: T, i: number) => void;
  empty?: string; flash?: Set<string>; active?: number;
}) {
  if (!rows.length) return <State>{empty}</State>;
  return (
    <div className="overflow-x-auto">
      <table className="w-max min-w-full border-collapse">
        <thead>
          <tr>{cols.map(c => (
            <th key={c.key} className={cx("sticky top-0 z-[2] border-b border-line bg-bg px-4 py-3 text-[11px] font-semibold text-muted",
              c.num ? "text-right" : "text-left")}>{c.head}</th>
          ))}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const k = rowKey(r, i);
            return (
              <tr key={k} onClick={onRow ? () => onRow(r, i) : undefined}
                className={cx(onRow && "cursor-pointer", "hover:[&>td]:bg-panel", flash?.has(k) && "flash", active === i && "[&>td]:bg-accent-wash")}>
                {cols.map(c => (
                  <td key={c.key} title={c.title?.(r)}
                    className={cx("max-w-[460px] truncate border-b border-line px-4 py-2.5 align-top font-mono text-[12px]", c.num && "text-right tabular-nums")}>
                    {c.cell(r)}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
