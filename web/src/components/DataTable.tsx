import type { ReactNode } from "react";
import { cx, State } from "./ui";

export interface Col<T> {
  key: string; head: string; cell: (row: T) => ReactNode; num?: boolean; title?: (row: T) => string;
  /** the column that leads a row on a phone (its first line), and the ones that ride in the meta line under it */
  lead?: boolean; meta?: boolean;
  /** a fixed width (Tailwind class) for short columns; with any width set the table lays out fixed and the lead column takes the rest */
  w?: string;
}

/** One list for every view in the hub. Desktop: a table with a sticky header, numbers right-aligned. Phone: each row is
 *  a two-line card (the lead column, then the rest as one meta line), so nothing scrolls sideways inside a card.
 *  `flash` marks rows new since the last render (Live), `active` the row the keyboard is on. */
export function DataTable<T>({ cols, rows, rowKey, onRow, empty = "Nothing yet.", flash, active }: {
  cols: Col<T>[]; rows: T[]; rowKey: (row: T, i: number) => string; onRow?: (row: T, i: number) => void;
  empty?: string; flash?: Set<string>; active?: number;
}) {
  if (!rows.length) return <State>{empty}</State>;
  const lead = cols.find(c => c.lead) ?? cols[cols.length - 1];
  const meta = cols.filter(c => c !== lead);
  const fixed = cols.some(c => c.w);
  return (
    <>
      <div className="hidden overflow-x-auto rounded-2xl border border-line bg-panel sm:block">
        <table className={cx("w-full border-collapse", fixed ? "table-fixed" : "min-w-max")}>
          <thead>
            <tr>{cols.map(c => (
              <th key={c.key} className={cx(c.w, "sticky top-0 z-[2] border-b border-line bg-panel px-5 py-3.5 text-xs font-bold tracking-[0.14em] text-muted uppercase",
                c.num ? "text-right" : "text-left")}>{c.head}</th>
            ))}</tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const k = rowKey(r, i);
              return (
                <tr key={k} onClick={onRow ? () => onRow(r, i) : undefined} tabIndex={onRow ? 0 : undefined} aria-current={active === i || undefined}
                  onKeyDown={onRow ? e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onRow(r, i); } } : undefined}
                  className={cx(onRow && "cursor-pointer transition-colors hover:[&>td]:bg-raised", flash?.has(k) && "flash", active === i && "[&>td]:bg-raised")}>
                  {cols.map(c => (
                    <td key={c.key} title={c.title?.(r)}
                      className={cx(fixed ? "" : "max-w-[520px]", "truncate border-b border-line px-5 py-2 align-top text-sm leading-[1.65] text-soft [tr:last-child>&]:border-b-0", c.num && "text-right font-mono tabular-nums")}>
                      {c.cell(r)}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <ul className="m-0 flex list-none flex-col gap-2 p-0 sm:hidden">
        {rows.map((r, i) => {
          const k = rowKey(r, i);
          return (
            <li key={k} onClick={onRow ? () => onRow(r, i) : undefined} tabIndex={onRow ? 0 : undefined}
              onKeyDown={onRow ? e => { if (e.key === "Enter") onRow(r, i); } : undefined}
              className={cx("rounded-xl border border-line bg-panel px-4 py-3", onRow && "cursor-pointer", flash?.has(k) && "flash")}>
              <div className="line-clamp-3 text-sm break-words text-text">{lead.cell(r)}</div>
              <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">{meta.map(c => <span key={c.key} className="min-w-0 truncate">{c.cell(r)}</span>)}</div>
            </li>
          );
        })}
      </ul>
    </>
  );
}
