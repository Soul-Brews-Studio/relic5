import { useEffect, useRef, useState } from "react";
import { usePoll } from "../api";
import { DataTable } from "../components/DataTable";
import { Hint, State, Who } from "../components/ui";
import type { TailResult, TailRow } from "../types";

const keyOf = (r: TailRow) => `${r.ts_th}|${r.role}|${r.sid}|${(r.text ?? "").slice(0, 40)}`;

/** The newest messages across machines, re-read every 15 s; rows that were not there last time flash green
 *  (lance-indexer ui/live.html). Rows arrive with each machine's push, so a quiet minute is normal. */
export function LiveView({ machine, on }: { machine: string; on: boolean }) {
  const p = usePoll<TailResult>(`/api/tail?n=80${machine ? "&machine=" + encodeURIComponent(machine) : ""}`, 15000, on);
  const seen = useRef<Set<string> | null>(null);
  const [fresh, setFresh] = useState<Set<string>>(new Set());
  useEffect(() => {
    if (!p.data) return;
    const keys = p.data.rows.map(keyOf);
    setFresh(seen.current ? new Set(keys.filter(k => !seen.current!.has(k))) : new Set());
    seen.current = new Set(keys);
  }, [p.data]);
  useEffect(() => { seen.current = null; }, [machine]);

  return (
    <>
      <Hint>{p.data ? `GET /api/tail · newest ${p.data.newest ?? "none"} · read ${p.at?.toLocaleTimeString()} · ${fresh.size} new since the last read` : "reading /api/tail…"}</Hint>
      {p.error && <State error>{p.error}</State>}
      <DataTable rows={p.data?.rows ?? []} rowKey={keyOf} flash={fresh} cols={[
        { key: "t", head: "time (+07)", cell: r => <time>{(r.ts_th ?? "").slice(5, 16).replace("T", " ")}</time> },
        { key: "m", head: "machine", cell: r => (r.machines ?? []).join(", ") },
        { key: "r", head: "role", cell: r => <Who role={r.role} /> },
        { key: "s", head: "session", cell: r => (r.session_name || r.sid || "").slice(0, 40), title: r => r.sid ?? "" },
        { key: "x", head: "text", cell: r => (r.text ?? "").replace(/\s+/g, " ").slice(0, 180), title: r => r.text ?? "" },
      ]} />
    </>
  );
}
