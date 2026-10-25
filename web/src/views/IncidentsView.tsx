// Every open incident on its own page, the text in full (Nat, 2026-10-25: "22 open incidents, needs a look: should
// click and open full page?"). The floating card hides on this page; the list is the same one.
import { IncidentRow, useIncidents } from "../components/Incidents";
import { PageHead, SectionHead } from "../components/ui";
import type { Status } from "../types";

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
    </>
  );
}
