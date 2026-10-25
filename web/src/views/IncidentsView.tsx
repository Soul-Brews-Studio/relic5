// Every open incident on its own page, the text in full (Nat, 2026-10-25: "22 open incidents, needs a look: should
// click and open full page?"). The floating card hides on this page; the list is the same one.
import { IncidentRow, useIncidents } from "../components/Incidents";
import { usePoll } from "../api";
import { ago, bkk, num } from "../format";
import { Chip, Hint, PageHead, SectionHead } from "../components/ui";
import type { Status } from "../types";

interface PageError { kind: string; message: string; count: number; first: string; last: string; views: string[]; stack: string; url: string }

/** What the hub page itself ran into (report.ts → /api/client-errors): grouped by message, newest first. */
function PageErrors() {
  const p = usePoll<{ groups: PageError[]; total: number }>("/api/client-errors?hours=24", 60_000);
  const g = p.data?.groups ?? [];
  return (
    <section className="mb-8">
      <SectionHead sub="errors this page ran into in your browsers, last 24 h: failed loads, a hub that did not answer, script errors">Page errors · {num(p.data?.total ?? 0)}</SectionHead>
      {!g.length ? <p className="m-0 rounded-2xl border border-line bg-panel px-5 py-4 text-sm text-ok">None in the last 24 hours.</p> : (
        <ol className="m-0 list-none overflow-hidden rounded-2xl border border-line bg-panel p-0">
          {g.map(e => (
            <li key={e.kind + e.message} className="border-b border-line px-5 py-3.5 last:border-b-0">
              <div className="flex flex-wrap items-center gap-2"><Chip tone={e.kind === "error" || e.kind === "rejection" ? "bad" : "warn"}>{e.kind}</Chip>
                <b className="text-sm text-text">{e.count}×</b><span className="text-xs text-muted">last {bkk(e.last)} ({ago(e.last)}) · {e.views.join(", ")}</span></div>
              <p className="m-0 mt-1.5 font-mono text-xs break-words text-soft">{e.message}</p>
              {e.stack && <details className="mt-1"><summary className="cursor-pointer text-xs text-muted">stack</summary>
                <pre className="m-0 mt-1 max-h-48 overflow-auto rounded-lg bg-deep p-3 font-mono text-xs whitespace-pre-wrap text-faint">{e.stack}</pre></details>}
            </li>))}
        </ol>)}
      <Hint>POST /api/client-error from the page (queued while the hub is away) · GET /api/client-errors · logs/client-errors.jsonl on the hub</Hint>
    </section>
  );
}

export function IncidentsView({ s, error }: { s: Status | null; error: string | null }) {
  const items = useIncidents(s, error);
  const failed = items.filter(i => i.level === "failed"), warn = items.filter(i => i.level !== "failed");
  const group = (title: string, sub: string, xs: typeof items) => xs.length > 0 && (
    <section className="mb-8">
      <SectionHead sub={sub}>{title} · {xs.length}</SectionHead>
      <ol className="m-0 list-none overflow-hidden rounded-2xl border border-line bg-panel p-0">
        {xs.map(i => <IncidentRow key={i.key} i={i} full />)}
      </ol>
    </section>
  );
  return (
    <>
      <PageHead title="Incidents" sub="What the hub says is wrong right now: failing and late checks first, then its own warnings. Each one goes away by itself when the hub no longer sees it." />
      {!items.length && <p className="m-0 rounded-2xl border border-line bg-panel px-5 py-4 text-sm text-ok">Nothing open: every check passes and the hub has no warnings.</p>}
      {group("Failing", "something stopped working", failed)}
      {group("Needs a look", "late, stale or out of step, still serving", warn)}
      <PageErrors />
    </>
  );
}
