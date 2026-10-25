import { ago, bytes, num, sum } from "../format";
import { DataTable } from "../components/DataTable";
import { PageHead, SectionHead } from "../components/ui";
import { Resources } from "../components/Resources";
import type { Status } from "../types";

type Line = { what: string; size: number | null; detail: string };

/** What the hub holds on disk and what it costs the machine (selfknow.py). */
export function StoreView({ s }: { s: Status }) {
  const st = s.store, w = s.watermarks;
  const lines: Line[] = [
    ...Object.entries(st.parts).map(([m, v]) => ({ what: `parts ${m}`, size: sum(v), detail: Object.entries(v).map(([k, x]) => `${k} ${bytes(x)}`).join(" · ") })),
    { what: "BM25 + vector tables", size: st.search_total, detail: Object.entries(st.search).map(([k, x]) => `${k} ${bytes(x)}`).join(" · ") },
    { what: "vector shards", size: sum(st.vectors), detail: Object.keys(st.vectors).join(", ") },
    { what: "logs", size: st.logs, detail: "" },
  ];
  return (
    <>
      <PageHead title="Store" sub="What the hub holds on white's disk, what it costs the machine, and how far each index has caught up." />
      <Resources s={s} />
      <DataTable rows={lines} rowKey={l => l.what} cols={[
        { key: "w", head: "what", cell: l => <b>{l.what}</b> },
        { key: "s", head: "size", num: true, cell: l => bytes(l.size) },
        { key: "d", head: "detail", lead: true, cell: l => l.detail, title: l => l.detail },
      ]} />
      <SectionHead>Watermarks</SectionHead>
      <DataTable rowKey={x => x.k} rows={[
        { k: "index (month manifests)", at: w.index.at, rows: num(w.index.rows) },
        { k: "BM25 generation", at: w.fts.at, rows: Object.entries(w.fts.rows).map(([k, v]) => `${k} ${num(v)}`).join(" · ") },
        { k: "vectors", at: w.vectors.at, rows: `pending ${num(w.vectors.pending)}` },
      ]} cols={[
        { key: "k", head: "watermark", cell: x => x.k },
        { key: "a", head: "at", cell: x => `${x.at ?? "none"} (${ago(x.at)})` },
        { key: "r", head: "rows", cell: x => x.rows, title: x => x.rows },
      ]} />
    </>
  );
}
