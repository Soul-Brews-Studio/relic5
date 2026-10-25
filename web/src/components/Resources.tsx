import { bytes } from "../format";
import { Stat } from "./ui";
import type { Status } from "../types";

/** What the hub holds and what it costs its machine (selfknow.py via /api/status): on the Disk page and on Home. */
export function Resources({ s }: { s: Status }) {
  const st = s.store, r = s.resources;
  return (
    <div className="mb-8 grid grid-cols-2 gap-x-8 gap-y-6 sm:grid-cols-3 lg:grid-cols-5">
      <Stat label="store" value={bytes(st.total)} note={st.growth?.per_day != null ? `+${bytes(st.growth.per_day)} a day since ${st.growth.since.slice(5)}` : "growth measured from tomorrow"} />
      <Stat label="disk free" value={`${st.disk.free_pct}%`} tone={st.disk.free_pct < 15 ? "bad" : st.disk.free_pct < 25 ? "warn" : undefined} note={`${bytes(st.disk.free)} of ${bytes(st.disk.total)}`} />
      <Stat label="memory available" value={bytes(r.memory?.available)} note={`of ${bytes(r.memory?.total)}`} />
      <Stat label="hub process" value={bytes(r.process?.rss)} note={`${r.process?.threads ?? "?"} threads · ${r.process?.open_files ?? "?"} files`} />
      <Stat label={`load · ${r.cpus} cpus`} value={r.load?.length ? r.load[0].toFixed(2) : "unknown"} note={r.load?.length ? `${r.load.slice(1).map(x => x.toFixed(2)).join(" · ")} (5, 15 min)` : undefined} />
    </div>
  );
}
