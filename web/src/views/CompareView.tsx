import { useState } from "react";
import { usePoll } from "../api";
import { bkk } from "../format";
import { DataTable } from "../components/DataTable";
import { Hint, PageHead, SectionHead, State } from "../components/ui";
import type { EvalRow } from "../types";

/** relic3 vs relic4 vs relic5 on the same known-item sets: the newest run of each method on each file. */
export function CompareView({ on }: { on: boolean }) {
  const p = usePoll<EvalRow[]>("/api/eval?n=500", 0, on);
  const [pick, setPick] = useState<EvalRow | null>(null);
  const last: Record<string, EvalRow> = {};
  for (const r of p.data ?? []) last[r.file + "|" + r.method] = r;
  const rows = Object.values(last).sort((a, b) => a.file.localeCompare(b.file) || b["recall@10"] - a["recall@10"]);
  return (
    <>
      <PageHead title="Compare" sub="Search quality on the same known-item sets: relic3, relic4 and relic5, the newest run of each method on each file. Click a row for its misses." />
      {p.error && <State error>{p.error}</State>}
      <DataTable rows={rows} rowKey={r => r.file + r.method} onRow={setPick} cols={[
        { key: "f", head: "file", cell: r => r.file },
        { key: "m", head: "method", lead: true, cell: r => <b>{r.method}</b> },
        { key: "n", head: "n", num: true, cell: r => r.n },
        { key: "r", head: "recall@10", num: true, cell: r => r["recall@10"] },
        { key: "p", head: "precision@10", num: true, cell: r => r["precision@10"] },
        { key: "mrr", head: "MRR", num: true, cell: r => r.mrr },
        { key: "p50", head: "p50 ms", num: true, cell: r => r.p50_ms },
        { key: "p95", head: "p95 ms", num: true, cell: r => r.p95_ms },
        { key: "x", head: "misses", num: true, cell: r => (r.misses ?? []).length },
        { key: "at", head: "at (+07)", cell: r => bkk(r.at) },
      ]} />
      <SectionHead>Misses of the selected run</SectionHead>
      {pick ? (pick.misses ?? []).map((m, i) => <div key={i} className="border-b border-line px-1 py-2.5 text-sm whitespace-pre-wrap text-soft last:border-b-0">{m}</div>)
        : <State>click a row</State>}
      <Hint>GET /api/eval (logs/eval.jsonl, appended by tests/eval/compare.py) · a hit = a top-10 result from the wanted session</Hint>
    </>
  );
}
