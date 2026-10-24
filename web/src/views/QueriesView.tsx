import { usePoll } from "../api";
import { bkk } from "../format";
import { DataTable, type Col } from "../components/DataTable";
import { Chip, Hint, PageHead, SectionHead, Stat, State, Stats } from "../components/ui";
import type { Queries, QueryRow } from "../types";

const cols: Col<QueryRow>[] = [
  { key: "at", head: "at (+07)", cell: r => <time>{bkk(r.at)}</time> },
  { key: "d", head: "door", cell: r => <Chip>{r.door}</Chip> },
  { key: "c", head: "client", cell: r => r.client ?? "" },
  { key: "t", head: "tool", cell: r => r.tool },
  { key: "q", head: "query", lead: true, cell: r => r.query, title: r => r.query },
  { key: "h", head: "hits", num: true, cell: r => r.hits ?? "" },
  { key: "ms", head: "ms", num: true, cell: r => r.ms ?? "" },
  { key: "e", head: "error", cell: r => (r.error ? <Chip tone="bad">{r.error}</Chip> : "") },
];

export function QueriesView({ on }: { on: boolean }) {
  const p = usePoll<Queries>("/api/queries", 15000, on);
  if (p.error && !p.data) return <State error>{p.error}</State>;
  if (!p.data) return <State>reading /api/queries…</State>;
  const q = p.data, hours = Object.entries(q.per_hour), last = hours[hours.length - 1]?.[1];
  return (
    <>
      <PageHead title="Queries" sub="Who asked the hub what, through which door, and how fast it answered. Zero-hit queries show what search still misses." />
      <Stats>
        <Stat label="running now" value={q.running.length} />
        <Stat label="last hour" value={last?.n ?? "unknown"} note={last ? `p50 ${last.p50_ms} ms · p95 ${last.p95_ms} ms` : undefined} />
        <Stat label="24 h" value={hours.reduce((a, [, v]) => a + v.n, 0)} />
        <Stat label="zero hits" value={q.zero_hits.length} tone={q.zero_hits.length ? "warn" : undefined} />
      </Stats>
      <SectionHead>Running now</SectionHead>
      <DataTable rows={q.running} rowKey={(r, i) => r.at + i} cols={cols.slice(0, 5)} empty="nothing running" />
      <SectionHead>Last 20</SectionHead>
      <DataTable rows={q.last} rowKey={(r, i) => r.at + i} cols={cols} />
      <SectionHead>Asked more than once</SectionHead>
      <DataTable rows={q.top} rowKey={r => r.query} cols={[{ key: "q", head: "query", cell: r => r.query }, { key: "n", head: "times", num: true, cell: r => r.n }]} />
      <SectionHead>Zero hits — what search misses</SectionHead>
      <DataTable rows={q.zero_hits} rowKey={(r, i) => r.at + i} cols={cols.slice(0, 5)} empty="none: every query found something" />
      <Hint>GET /api/queries · logs/queries.jsonl on the hub only (0600), never in git</Hint>
    </>
  );
}
