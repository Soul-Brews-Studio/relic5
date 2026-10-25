// How the hub read this search (Nat, 2026-10-25: "can we show like how we tokenize? visualize"): the query as the
// BM25 index's tokens (GET /api/explain: lance's ICU tokenizer with the index's settings), each token's weight, and a
// matrix of the top hits by token, so a reader sees why a hit ranks where it does. Colours are the tokens' own
// (tokenHue), the same as the highlights in every hit.
import { useState } from "react";
import { compact, num } from "../format";
import type { Explain, Hit } from "../types";
import { cx, tokenHue } from "./ui";

export function SearchExplain({ e, hits, active, pick, mapHref }: {
  e: Explain; hits: Hit[]; active: number; pick: (i: number) => void; mapHref: string | null;
}) {
  const [open, setOpen] = useState(() => localStorage.getItem("relic5-explain") !== "0");
  const toggle = () => { localStorage.setItem("relic5-explain", open ? "0" : "1"); setOpen(!open); };
  const terms = e.terms, top = Math.max(0.001, ...terms.map(t => t.idf ?? 0));
  const shown = hits.slice(0, 24), best = Math.max(0.001, ...shown.map(h => h.score));
  const rare = [...terms].sort((a, b) => (b.idf ?? 0) - (a.idf ?? 0))[0];
  return (
    <section aria-label="How this search reads" className="mx-5 mb-4 rounded-xl border border-line bg-deep">
      <button type="button" onClick={toggle} aria-expanded={open}
        className="flex min-h-11 w-full flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-left">
        <span className="text-sm font-bold text-text">How this search reads</span>
        <span className="flex flex-wrap gap-1">{e.tokens.map((t, i) => (
          <span key={t + i} className="rounded px-1.5 font-mono text-xs" style={{ background: `color-mix(in srgb, ${tokenHue(terms.findIndex(x => x.token === t))} 22%, transparent)`, color: "var(--text)" }}>{t}</span>))}</span>
        <span className="ml-auto text-xs text-muted">{open ? "hide" : "show"}</span>
      </button>
      {open && (
        <div className="border-t border-line px-4 pt-3 pb-4">
          <p className="m-0 mb-3 max-w-[78ch] text-sm text-muted">
            The index cut your words into <b className="text-soft">{e.tokens.length} tokens</b> ({e.tokenizer}).
            {e.tokens.length > 1 && <> It first looked for them as one exact phrase{e.phrase_rows != null && <>: <b className="text-soft">{num(e.phrase_rows)}</b> {e.phrase_rows === 1 ? "row has it" : "rows have it"}</>}, then for any of them.</>}{" "}
            A rare token weighs more than a common one{rare && terms.length > 1 && <>: here <b className="text-soft">{rare.token}</b> counts most</>}. Out of {compact(e.rows)} rows.
          </p>
          <div className="grid gap-2" role="table" aria-label="Tokens, the rows that hold each, and its weight">
            {terms.map((t, i) => (
              <div key={t.token} role="row" className="grid grid-cols-[minmax(0,9rem)_minmax(0,1fr)_6.5rem] items-center gap-3 text-sm">
                <span role="cell" className="flex min-w-0 items-center gap-2"><i className="size-2.5 flex-none rounded-sm" style={{ background: tokenHue(i) }} /><span className="truncate font-mono text-text">{t.token}</span></span>
                <span role="cell" className="h-2 rounded-full bg-raised" title={`weight ${t.idf ?? "?"} (idf)`}>
                  <span className="block h-2 rounded-full" style={{ width: `${Math.max(3, (100 * (t.idf ?? 0)) / top)}%`, background: tokenHue(i) }} />
                </span>
                <span role="cell" className="text-right font-mono text-xs text-muted tabular-nums">{t.capped ? `${compact(t.rows)}+` : compact(t.rows)} rows</span>
              </div>
            ))}
          </div>
          <p className="m-0 mt-1 text-xs text-faint">bar: weight (BM25 idf, rarer is longer) · rows: how many messages hold the token</p>

          {shown.length > 0 && shown.some(h => h.matched) && (
            <div className="mt-5">
              <div className="mb-2 flex flex-wrap items-baseline gap-x-3"><span className="text-sm font-bold text-text">What each hit matched</span><span className="text-xs text-muted">the top {shown.length}, best first · click a row to read it</span></div>
              <div className="overflow-x-auto">
                <table className="border-separate border-spacing-y-0.5 text-xs">
                  <thead><tr>
                    <th className="w-8 pr-2 text-right font-normal text-faint">#</th>
                    {terms.map((t, i) => <th key={t.token} className="px-0.5 pb-1 align-bottom font-mono font-normal" style={{ color: tokenHue(i) }}><span className="block max-w-14 truncate" title={t.token}>{t.token}</span></th>)}
                    <th className="pl-3 text-left font-normal text-faint">score</th>
                  </tr></thead>
                  <tbody>{shown.map((h, n) => {
                    const m = new Set(h.matched ?? []);
                    return (
                      <tr key={h.uid + n} onClick={() => pick(n)} className={cx("cursor-pointer", n === active && "[&>td]:bg-raised")}>
                        <td className="rounded-l pr-2 text-right font-mono text-faint tabular-nums">{n + 1}</td>
                        {terms.map((t, i) => (
                          <td key={t.token} className="px-0.5 text-center">
                            <span className="mx-auto block size-3.5 rounded-[3px]" title={`${t.token}: ${m.has(t.token) ? "in this hit" : "not in it"}`}
                              style={m.has(t.token) ? { background: tokenHue(i) } : { boxShadow: "inset 0 0 0 1px var(--line-strong)" }} />
                          </td>))}
                        <td className="rounded-r pl-3"><span className="flex items-center gap-2"><span className="h-1.5 w-20 rounded-full bg-raised"><span className="block h-1.5 rounded-full bg-soft" style={{ width: `${(100 * h.score) / best}%` }} /></span><span className="font-mono text-faint tabular-nums">{h.score.toFixed(2)}</span></span></td>
                      </tr>
                    );
                  })}</tbody>
                </table>
              </div>
            </div>
          )}
          {mapHref && <a href={mapHref} className="mt-4 inline-flex min-h-11 items-center rounded-lg px-2 text-sm font-semibold text-accent hover:bg-raised">See these hits' sessions on the Map, in 3D</a>}
          <p className="m-0 mt-2 font-mono text-xs text-faint">GET /api/explain · {e.ms} ms</p>
        </div>
      )}
    </section>
  );
}
