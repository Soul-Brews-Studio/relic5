import { useEffect, useRef, useState } from "react";
import { get, usePoll } from "../api";
import { bkk, clock, repoColor } from "../format";
import { Drawer } from "../components/Drawer";
import { Loading, MachinePick } from "../components/ui";
import { DataTable } from "../components/DataTable";
import { Hint, PageHead, State, Who } from "../components/ui";
import { Context, shortRepo, WhoPick } from "./SearchView";
import type { ShowResult, TailResult, TailRow } from "../types";

const keyOf = (r: TailRow) => `${r.ts_th}|${r.role}|${r.sid}|${(r.text ?? "").slice(0, 40)}`;

/** The newest messages across machines, re-read every 15 s; rows that were not there last time flash amber
 *  (lance-indexer ui/live.html). Rows arrive with each machine's push, so a quiet minute is normal. */
export function LiveView({ machine, role = "", on, machines, setMachine, setRole }:
  { machine: string; role?: string; on: boolean; machines: string[]; setMachine: (m: string) => void; setRole: (r: string) => void }) {
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
  const [open, setOpen] = useState<{ r: TailRow; show: ShowResult | null; err?: string } | null>(null);
  const read = (r: TailRow) => {
    if (!r.link) return;
    setOpen({ r, show: null });
    get<ShowResult>(`/api/show?id=${encodeURIComponent(r.link)}&before=3&after=3`).then(show => setOpen(o => o && o.r === r ? { r, show } : o))
      .catch(e => setOpen(o => o && o.r === r ? { r, show: null, err: String(e.message ?? e) } : o));
  };

  return (
    <>
      <PageHead title="Live" sub="The newest messages from every machine, read again every 15 seconds. New rows glow amber; a quiet minute is normal, rows arrive with each push.">
        <WhoPick role={role} onChange={setRole} />
        <MachinePick machine={machine} machines={machines} onChange={setMachine} />
      </PageHead>
      <Hint>{p.data ? `GET /api/tail · newest ${bkk(p.data.newest)} · read ${clock(p.at)} · ${fresh.size} new since the last read` : "reading /api/tail…"}</Hint>
      {p.error && <State error>{p.error}</State>}
      <DataTable rows={(p.data?.rows ?? []).filter(r => !role || r.role === role)} rowKey={keyOf} flash={fresh} onRow={read} cols={[
        { key: "t", head: "time (+07)", w: "w-32", cell: r => <time>{(r.ts_th ?? "").slice(5, 16).replace("T", " ")}</time> },
        { key: "m", head: "machine", w: "w-28", cell: r => (r.machines ?? []).join(", ") },
        { key: "r", head: "who", w: "w-32", cell: r => <Who role={r.role} /> },
        // repo first: a title is the session's first one ("Restart self" stays after the session moves on to other work)
        { key: "s", head: "session", w: "w-[19rem]", cell: r => {
            const repo = r.cat && r.cat !== "home / other" ? shortRepo(r.cat) : "";
            const name = (r.session_name || r.sid || "").slice(0, 40);
            return repo ? <><span className="mr-2 inline-block size-2 rounded-full align-middle" style={{ background: repoColor(repo) }} /><span style={{ color: repoColor(repo) }}>{repo.slice(0, 24)}</span><span className="text-muted"> · </span>{name}</> : name;
          }, title: r => `${r.cat ?? ""} · ${r.session_name ?? ""} · ${r.sid ?? ""}` },
        { key: "x", head: "text", lead: true, cell: r => (r.text ?? "").replace(/\s+/g, " ").slice(0, 180), title: r => r.text ?? "" },
      ]} />
      <Drawer open={!!open} onClose={() => setOpen(null)} title={open ? <>{open.r.cat ? shortRepo(open.r.cat) + " · " : ""}{open.r.session_name ?? open.r.sid}</> : ""}
        note={open?.r.link} onCopy={() => open?.r.link && navigator.clipboard.writeText(open.r.link)}>
        {open?.err ? <State error>{open.err}</State> : open?.show ? <Context r={open.show} q="" /> : <Loading label="Reading the message" />}
      </Drawer>
    </>
  );
}
