import type { ReactNode } from "react";
import type { Status } from "../types";
import { ago, bytes, num, secs, sum } from "../format";
import { Chip, cx, Lbl, type Tone } from "./ui";

function Section({ title, note, children }: { title: string; note?: ReactNode; children: ReactNode }) {
  return (
    <section className="border-b border-line px-4 py-3.5">
      <div className="mb-2.5 flex items-baseline justify-between gap-2"><Lbl>{title}</Lbl><span className="truncate text-[10px] text-faint">{note}</span></div>
      <div className="flex flex-col gap-1">{children}</div>
    </section>
  );
}

/** One rail entry: a name, a count on the right, a detail line under it. Pressed = it filters the pane. */
export function RailItem({ name, count, detail, pressed, onClick }:
  { name: ReactNode; count?: ReactNode; detail?: ReactNode; pressed?: boolean; onClick?: () => void }) {
  return (
    <button type="button" aria-pressed={pressed} onClick={onClick}
      className={cx("grid w-full grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-2 gap-y-0.5 rounded-[5px] border px-2.5 py-2 text-left text-soft",
        pressed ? "border-accent-dim bg-accent-wash text-text" : "border-transparent hover:border-line hover:bg-panel")}>
      <b className={cx("truncate text-xs font-semibold", pressed && "text-accent")}>{name}</b>
      <span className="text-[11px] tabular-nums text-muted">{count}</span>
      {detail && <small className="col-span-2 truncate text-[10px] text-faint">{detail}</small>}
    </button>
  );
}

export function Ledger({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="m-0 grid grid-cols-[auto_minmax(0,1fr)] gap-x-2.5 gap-y-1.5 text-[11px]">
      {rows.map(([k, v]) => [
        <dt key={k + "k"} className="m-0 text-muted">{k}</dt>,
        <dd key={k + "v"} className="m-0 truncate text-right text-soft">{v}</dd>,
      ])}
    </dl>
  );
}

/** "2026-10-24 07:44:42 SYNC OK  text|…" -> tone and the time. */
export function syncChip(line?: string): { tone: Tone; text: string } {
  if (!line) return { tone: "dim", text: "no chain log" };
  const t = line.slice(11, 16);
  return line.includes("MISMATCH") ? { tone: "bad", text: `MISMATCH ${t}` } : { tone: "ok", text: `SYNC ${t}` };
}

export function Rail({ s, machine, setMachine }: { s: Status; machine: string; setMachine: (m: string) => void }) {
  const names = Object.keys({ ...s.machines, ...s.versions }).sort();
  const shown = s.months.list.filter(m => m.rows.text + m.rows.tools > 0), open = shown.filter(m => !m.sealed).length;
  const w = s.watermarks, st = s.store, r = s.resources;
  return (
    <aside className="min-h-0 overflow-y-auto border-r border-line bg-rail">
      <Section title="Machines" note={`${names.length} pushing`}>
        <RailItem name="all machines" count={num(sum(Object.fromEntries(names.map(n => [n, s.machines[n]?.text?.rows ?? 0]))))}
          pressed={!machine} onClick={() => setMachine("")} detail="text rows, folded per machine" />
        {names.map(n => {
          const f = s.freshness.machines[n] ?? {}, v = s.versions[n] ?? {}, c = syncChip(f.sync);
          return (
            <RailItem key={n} name={n} count={num(s.machines[n]?.text?.rows)} pressed={machine === n} onClick={() => setMachine(machine === n ? "" : n)}
              detail={<span className="flex items-baseline gap-1.5"><Chip tone={c.tone}>{c.text}</Chip>
                <span>pushed {ago(f.pushed_at)}</span><span>· {v["relic-scan"] ?? "no versions"}</span></span>} />
          );
        })}
      </Section>
      <Section title="Months" note={`${s.months.sealed} sealed · ${open} open`}>
        {shown.slice().reverse().map(m => (
          <RailItem key={m.month} name={m.month} count={num(m.rows.text)}
            detail={<span className="flex gap-1.5">{m.sealed ? <Chip>sealed</Chip> : <Chip tone="ok">open</Chip>}
              <span>tools {num(m.rows.tools)} · thinking {num(m.rows.thinking)}</span></span>} />
        ))}
      </Section>
      <Section title="Hub">
        <Ledger rows={[
          ["home", s.home], ["code", `${s.code.name} ${s.code.version}`], ["door", s.you],
          ["index", ago(w.index.at)], ["BM25", s.freshness.fts ? `${secs(s.freshness.fts.age_s)} old` : "none"],
          ["vectors pending", num(w.vectors.pending)], ["store", bytes(st.total)],
          ["disk free", `${bytes(st.disk.free)} (${st.disk.free_pct}%)`],
          ["last backup", s.backup?.at ? `${ago(s.backup.at)} · ${bytes(s.backup.bytes)}` : "none yet"],
          ["load", (r.load ?? []).map(x => x.toFixed(2)).join(" / ") + ` · ${r.cpus} cpu`],
        ]} />
      </Section>
    </aside>
  );
}
