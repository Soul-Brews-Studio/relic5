// Hours (Nat, 2026-10-26: "i want that in our system how? ... can we display the odin 2 skills output?"). One Bangkok
// day, newest hour first: Huginn's hourly flight (odin-oracle's /huginn, ψ/memory/huginn/<date>/<HH>00_works.md) on
// the left, and what the models made of the same hour on the right (relic-extract's readings: z.ai glm-5.3 and gb300
// qwen3:14b, 1h, 3h and 15m windows). The day's roll-ups and Munin's searches sit above. GET /api/hours?date=.
import { useState } from "react";
import { usePoll } from "../api";
import { ago, bkk, num } from "../format";
import { Markdown } from "../components/Markdown";
import { Btn, Chip, cx, Hint, Lbl, Loading, PageHead, SectionHead, State } from "../components/ui";

interface Reading {
  grain: string; start: string; end: string; model: string; deep: boolean; at: string; type?: string; focus?: string;
  work?: string[]; distraction?: string; friction?: string; lesson?: string; en?: string; th?: string; pattern?: string;
}
interface Note { path: string; cat: string; ts: string; title: string; text: string }
interface Day { date: string; daily: Note | null; day: Reading[]; munin: Note[]; hours: { hour: string; huginn: Note | null; readings: Reading[] }[];
  notes_newest: string | null; readings_files: string[] }
interface Days { days: { date: string; huginn: number; readings: number }[] }

interface MonthRow { month: string; days_read: number; huginn_daily: number; day_types: Record<string, number>; recap: boolean }
interface MonthDay { date: string; huginn: string | null; models: { model: string; type?: string; focus?: string }[] }

/** Day types in a fixed order and colour (never cycled): what the models called each day. */
const TYPES: [string, string][] = [["build", "var(--accent)"], ["mixed", "var(--amber)"], ["research", "var(--tool)"], ["ops", "var(--ok)"],
  ["fix", "var(--danger)"], ["writing", "var(--code)"]];
const typeColor = (t?: string) => TYPES.find(x => x[0] === t)?.[1] ?? "var(--muted)";

/** Every month as one stacked bar (day readings by type), oldest left; a month opens as a strip of its days, a day
 *  opens the hour-by-hour view below (GET /api/hours/months). */
function Overall({ on, pick }: { on: boolean; pick: (d: string) => void }) {
  const all = usePoll<{ months: MonthRow[] }>("/api/hours/months", 0, on);
  const [month, setMonth] = useState<string | null>(null);
  const one = usePoll<{ month: string; recap: string | null; days: MonthDay[] }>(month ? `/api/hours/months?month=${month}` : null, 0, on);
  const ms = [...(all.data?.months ?? [])].reverse();
  if (!ms.length) return null;
  const max = Math.max(...ms.map(m => Object.values(m.day_types).reduce((a, b) => a + b, 0)), 1);
  const H = 120, W = 34, G = 10;
  return (
    <section className="mb-10">
      <SectionHead sub="Each bar is a month: the day readings of gb300 and z.ai, by what kind of day they called it. Click a month for its days.">Overall</SectionHead>
      <div className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
        {TYPES.map(([t, c]) => <span key={t} className="inline-flex items-center gap-1.5"><span className="size-2.5 rounded-sm" style={{ background: c }} />{t}</span>)}
        <span className="inline-flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-muted" />other</span>
      </div>
      <div className="overflow-x-auto">
        <svg width={ms.length * (W + G)} height={H + 40} role="img" aria-label="Day readings per month by type">
          {ms.map((m, i) => {
            let y = H;
            const x = i * (W + G), on = m.month === month;
            const segs = [...TYPES.map(t => t[0]), ...Object.keys(m.day_types).filter(t => !TYPES.some(x => x[0] === t))];
            const total = Object.values(m.day_types).reduce((a, b) => a + b, 0);
            return (
              <g key={m.month} onClick={() => setMonth(on ? null : m.month)} className="cursor-pointer">
                <title>{`${m.month}: ${m.days_read} days read, ${m.huginn_daily} Huginn daily, ${Object.entries(m.day_types).map(([k, v]) => `${k} ${v}`).join(", ")}`}</title>
                <rect x={x - 3} y={0} width={W + 6} height={H + 36} rx={6} fill={on ? "var(--accent-wash)" : "transparent"} />
                {segs.map(t => {
                  const v = m.day_types[t] ?? 0;
                  if (!v) return null;
                  const h = (v / max) * H; y -= h;
                  return <rect key={t} x={x} y={y + 1} width={W} height={Math.max(h - 2, 1)} rx={2} fill={typeColor(t)} />;
                })}
                <text x={x + W / 2} y={H + 14} textAnchor="middle" className="fill-[var(--muted)] font-mono" fontSize={10}>{m.month.slice(2)}</text>
                <text x={x + W / 2} y={H + 28} textAnchor="middle" className="fill-[var(--faint)] font-mono" fontSize={9}>{m.huginn_daily ? `H${m.huginn_daily}` : total ? "" : "·"}</text>
              </g>
            );
          })}
        </svg>
      </div>
      <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <MonthlyMessages on={on} />
        <WhenTyping on={on} />
      </div>
      <div className="mt-6"><AiUsage on={on} /></div>
      {month && one.data && (
        <div className="mt-4 rounded-2xl border border-line bg-panel p-5">
          <div className="mb-3 flex items-baseline gap-3"><b className="font-mono text-lg text-text">{month}</b>
            <span className="text-xs text-muted">{one.data.days.length} days · {one.data.recap ? "sealed recap below" : "no sealed recap yet"} · square = the day's type, dot = Huginn wrote a daily</span></div>
          <div className="flex flex-wrap gap-1.5">
            {one.data.days.map(d => {
              const z = d.models.find(m => m.model.startsWith("zai")) ?? d.models[0];
              return (
                <button key={d.date} type="button" onClick={() => pick(d.date)} title={`${d.date} · ${z?.type ?? "not read"} · ${z?.focus ?? ""}`}
                  className="relative grid size-9 place-items-center rounded-md font-mono text-xs font-bold text-[var(--deep)] hover:outline hover:outline-2 hover:outline-[var(--text)]"
                  style={{ background: z ? typeColor(z.type) : "var(--raised)" }}>
                  {d.date.slice(8)}{d.huginn && <span className="absolute -top-0.5 -right-0.5 size-2 rounded-full border border-[var(--panel)] bg-[var(--text)]" />}
                </button>);
            })}
          </div>
          {one.data.recap && <details className="mt-4"><summary className="cursor-pointer text-sm font-semibold text-accent">The month's sealed recap</summary>
            <div className="mt-3 max-w-[80ch] text-sm"><Markdown text={one.data.recap} /></div></details>}
        </div>)}
    </section>
  );
}

interface Act { buckets: string[]; series: { name: string; total: number; counts: Record<string, number> }[]; total: number }

/** Messages per month, typed by Nat (role user) against written by an agent, as two bars side by side. */
function MonthlyMessages({ on }: { on: boolean }) {
  const a = usePoll<Act>("/api/activity?by=month&group=role", 0, on);
  const d = a.data;
  if (!d?.buckets.length) return null;
  const get = (n: string, b: string) => d.series.find(s => s.name === n)?.counts[b] ?? 0;
  const max = Math.max(...d.buckets.map(b => Math.max(get("user", b), get("assistant", b))), 1);
  const H = 140, W = 14, G = 14;
  return (
    <div className="min-w-0">
      <div className="mb-2 flex flex-wrap items-center gap-x-4 text-xs text-muted">
        <b className="text-soft">Messages per month</b>
        <span className="inline-flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-[var(--user)]" />typed by Nat</span>
        <span className="inline-flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-[var(--assistant)]" />written by an agent</span>
      </div>
      <div className="overflow-x-auto">
        <svg width={d.buckets.length * (2 * W + G)} height={H + 22} role="img" aria-label="Messages per month by who wrote them">
          {d.buckets.map((b, i) => {
            const x = i * (2 * W + G), u = get("user", b), as = get("assistant", b);
            return (
              <g key={b}>
                <title>{`${b}: ${num(u)} typed by Nat, ${num(as)} by agents`}</title>
                <rect x={x} y={H - (u / max) * H} width={W - 2} height={Math.max((u / max) * H, 1)} rx={2} fill="var(--user)" />
                <rect x={x + W} y={H - (as / max) * H} width={W - 2} height={Math.max((as / max) * H, 1)} rx={2} fill="var(--assistant)" />
                <text x={x + W} y={H + 14} textAnchor="middle" fontSize={9} className="fill-[var(--muted)] font-mono">{b.slice(2)}</text>
              </g>);
          })}
        </svg>
      </div>
    </div>
  );
}

interface UsageRow { period: string; engine: string; sessions: number; subagents: number; tool_calls: number; tool_errors: number }
const ENGINES: [string, string][] = [["claude", "var(--assistant)"], ["codex", "var(--ok)"], ["omp", "var(--tool)"], ["thclaws", "var(--code)"]];

/** AI usage since the first month (GET /api/usage, MCP relic_usage): sessions per month by engine, subagents inside. */
function AiUsage({ on }: { on: boolean }) {
  const u = usePoll<{ rows: UsageRow[]; totals: Record<string, number> }>("/api/usage?by=month&group=engine", 0, on);
  const rows = u.data?.rows ?? [];
  if (!rows.length) return null;
  const months = [...new Set(rows.map(r => r.period))].sort();
  const tot = (m: string) => rows.filter(r => r.period === m).reduce((a, r) => a + r.sessions + r.subagents, 0);
  const max = Math.max(...months.map(tot), 1);
  const H = 140, W = 26, G = 8;
  const t = u.data!.totals;
  return (
    <div className="min-w-0">
      <div className="mb-2 flex flex-wrap items-center gap-x-4 text-xs text-muted">
        <b className="text-soft">AI sessions per month, by engine</b>
        {ENGINES.map(([e, c]) => <span key={e} className="inline-flex items-center gap-1.5"><span className="size-2.5 rounded-sm" style={{ background: c }} />{e}</span>)}
        <span>· {num(t.sessions)} sessions, {num(t.subagents)} subagents, {num(t.tool_calls)} tool calls ({((t.tool_errors / Math.max(t.tool_calls, 1)) * 100).toFixed(1)}% errors)</span>
      </div>
      <div className="overflow-x-auto">
        <svg width={months.length * (W + G)} height={H + 22} role="img" aria-label="AI sessions per month by engine">
          {months.map((m, i) => {
            let y = H;
            return (
              <g key={m}>
                <title>{rows.filter(r => r.period === m).map(r => `${r.engine}: ${num(r.sessions)} sessions + ${num(r.subagents)} subagents, ${num(r.tool_calls)} tool calls`).join("\n")}</title>
                {ENGINES.map(([e, c]) => {
                  const r = rows.find(x => x.period === m && x.engine === e);
                  const v = r ? r.sessions + r.subagents : 0;
                  if (!v) return null;
                  const h = Math.max((v / max) * H, 1.5); y -= h;
                  return <rect key={e} x={i * (W + G)} y={y} width={W} height={h - 1} rx={2} fill={c} />;
                })}
                <text x={i * (W + G) + W / 2} y={H + 14} textAnchor="middle" fontSize={9} className="fill-[var(--muted)] font-mono">{m.slice(2)}</text>
              </g>);
          })}
        </svg>
      </div>
    </div>
  );
}

/** When Nat types: weekday (rows) by hour of day (columns), one cell per pair, darker = more. */
function WhenTyping({ on }: { on: boolean }) {
  const a = usePoll<Act>("/api/activity?by=hour_of_day&role=user", 0, on);
  const w = usePoll<Act>("/api/activity?by=weekday&role=user", 0, on);
  const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const hours = a.data?.series[0]?.counts ?? {};
  const wk = w.data?.series[0]?.counts ?? {};
  if (!a.data?.total) return null;
  // scaled from the quietest to the busiest, not from zero: every hour has typing, so a zero base reads as flat
  const scale = (o: Record<string, number>) => { const v = Object.values(o); const lo = Math.min(...v), hi = Math.max(...v);
    return (n: number) => 0.1 + 0.9 * (hi > lo ? (n - lo) / (hi - lo) : 1); };
  const hs = scale(hours), ws = scale(wk);
  return (
    <div className="min-w-0">
      <div className="mb-2 text-xs text-muted"><b className="text-soft">When Nat types</b> · by hour of day (Bangkok) and by weekday, all time · faint = the quietest, full = the busiest</div>
      <div className="flex gap-[3px]">
        {Array.from({ length: 24 }, (_, h) => String(h).padStart(2, "0")).map(h => (
          <div key={h} className="flex flex-col items-center gap-1" title={`${h}:00 · ${num(hours[h] ?? 0)} typed`}>
            <div className="h-16 w-3.5 rounded-sm" style={{ background: "var(--user)", opacity: hs(hours[h] ?? 0) }} />
            <span className="font-mono text-[9px] text-faint">{h}</span>
          </div>))}
      </div>
      <div className="mt-3 flex gap-1.5">
        {days.map((dn, i) => (
          <div key={dn} className="flex flex-col items-center gap-1" title={`${dn} · ${num(wk[String(i + 1)] ?? 0)} typed`}>
            <div className="h-6 w-9 rounded-sm" style={{ background: "var(--user)", opacity: ws(wk[String(i + 1)] ?? 0) }} />
            <span className="text-[10px] text-faint">{dn}</span>
          </div>))}
      </div>
    </div>
  );
}

const today = () => new Date(Date.now() + 7 * 3600e3).toISOString().slice(0, 10);
const shift = (d: string, n: number) => new Date(Date.parse(d + "T00:00:00Z") + n * 86400e3).toISOString().slice(0, 10);
const said = (s?: string) => !!s && s.trim().toLowerCase() !== "none";
const short = (m: string) => m.replace(/^gb300:/, "gb300 · ").replace(/^zai:/, "z.ai · ");

function ReadingCard({ r }: { r: Reading }) {
  const [th, setTh] = useState(false);
  return (
    <article className="border-b border-line py-4 first:pt-0 last:border-b-0 last:pb-0">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Chip tone={r.model.startsWith("zai") ? "live" : "dim"}>{short(r.model)}{r.deep ? " · deep" : ""}</Chip>
        <span className="font-mono text-xs text-muted">{r.grain} · {r.start.slice(11)}–{r.end.slice(11)}</span>
        {r.type && <span className="text-xs font-semibold text-amber">{r.type}</span>}
        {r.th && <button type="button" onClick={() => setTh(!th)} className="ml-auto min-h-8 text-xs font-semibold text-accent">{th ? "EN" : "ไทย"}</button>}
      </div>
      {th ? <p className="m-0 text-sm leading-relaxed text-soft">{r.th}</p> : <>
        <p className="m-0 text-sm leading-relaxed text-text">{r.focus}</p>
        {!!r.work?.length && <ul className="m-0 mt-2 list-disc space-y-1 pl-5 text-sm text-soft">{r.work.map((w, i) => <li key={i}>{w}</li>)}</ul>}
        {said(r.distraction) && <p className="m-0 mt-2 text-sm text-muted"><b className="text-soft">Distraction</b> · {r.distraction}</p>}
        {said(r.friction) && <p className="m-0 mt-1 text-sm text-muted"><b className="text-soft">Friction</b> · {r.friction}</p>}
        {said(r.lesson) && <p className="m-0 mt-1 text-sm text-muted"><b className="text-ok">Lesson</b> · {r.lesson}</p>}
      </>}
    </article>
  );
}

function Flight({ n, open }: { n: Note; open?: boolean }) {
  const [all, setAll] = useState(!!open);
  const head = n.text.replace(/^---[\s\S]*?\n---\n/, "");
  return (
    <div>
      <div className={cx("relative", !all && "max-h-[28rem] overflow-hidden")}>
        <div className="max-w-[80ch] text-sm"><Markdown text={head} /></div>
        {!all && <div aria-hidden className="pointer-events-none absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t from-[var(--panel)] to-transparent" />}
      </div>
      <button type="button" onClick={() => setAll(!all)} className="mt-2 min-h-9 text-xs font-semibold text-accent">{all ? "Show less" : "Read the whole flight"}</button>
    </div>
  );
}

export function HoursView({ on }: { on: boolean }) {
  const [date, setDate] = useState(today());
  const d = usePoll<Day>(`/api/hours?date=${date}`, 120_000, on);
  const days = usePoll<Days>("/api/hours/days", 0, on);
  const x = d.data;
  return (
    <>
      <PageHead title="Hours" sub="One day hour by hour: Huginn's hourly flight beside what z.ai and gb300 made of the same hour. Huginn and Munin come from odin-oracle's ψ; the readings come from relic-extract.">
        <Btn onClick={() => setDate(shift(date, -1))} aria-label="The day before">‹</Btn>
        <input type="date" value={date} max={today()} onChange={e => e.target.value && setDate(e.target.value)}
          className="h-11 rounded-lg border border-line bg-deep px-3 font-mono text-sm text-text" aria-label="Day" />
        <Btn onClick={() => setDate(shift(date, 1))} disabled={date >= today()} aria-label="The day after">›</Btn>
        <Btn onClick={() => setDate(today())} disabled={date === today()}>Today</Btn>
      </PageHead>
      {!!days.data?.days.length && (
        <div className="mb-8 flex flex-wrap gap-1.5" aria-label="Days with flights or readings">
          {days.data.days.slice(0, 21).map(c => (
            <button key={c.date} type="button" onClick={() => setDate(c.date)} title={`${c.huginn} Huginn flights · ${num(c.readings)} readings`}
              className={cx("min-h-9 rounded-lg border px-2.5 font-mono text-xs", c.date === date ? "border-accent bg-accent-wash text-accent" : "border-line text-muted hover:border-line-strong hover:text-text")}>
              {c.date.slice(5)}<span className="ml-1.5 text-faint">{c.huginn || "·"}/{c.readings ? num(c.readings) : "·"}</span>
            </button>))}
        </div>)}
      <Overall on={on} pick={x => { setDate(x); requestAnimationFrame(() => document.getElementById("hours-day")?.scrollIntoView({ behavior: "smooth" })); }} />
      <div id="hours-day" />
      {d.error && <State error>{d.error}</State>}
      {!x && !d.error && <Loading label="Reading the day" />}
      {x && <>
        {(x.daily || x.day.length > 0) && <>
          <SectionHead sub="Huginn's roll-up of the day, and the day as each model read it">The day</SectionHead>
          <div className="grid gap-4 lg:grid-cols-2">
            <section className="min-w-0 rounded-2xl border border-line bg-panel p-6">
              <Lbl>Huginn · daily</Lbl>
              <div className="mt-3">{x.daily ? <Flight n={x.daily} /> : <p className="m-0 text-sm text-muted">No roll-up for this day.</p>}</div>
            </section>
            <section className="min-w-0 rounded-2xl border border-line bg-panel p-6">
              <Lbl>Models · day</Lbl>
              <div className="mt-3">{x.day.length ? x.day.map(r => <ReadingCard key={r.model + r.deep} r={r} />) : <p className="m-0 text-sm text-muted">Not read yet.</p>}</div>
            </section>
          </div>
        </>}
        {x.munin.length > 0 && <>
          <SectionHead sub="odin-oracle's /munin: where something lives across roots, sessions and vaults">Munin</SectionHead>
          <div className="grid gap-4 lg:grid-cols-2">{x.munin.map(n => (
            <section key={n.path} className="min-w-0 rounded-2xl border border-line bg-panel p-6"><Lbl>{n.title}</Lbl><div className="mt-3"><Flight n={n} /></div></section>))}</div>
        </>}
        <SectionHead sub={`${x.hours.length} hours · notes as of ${bkk(x.notes_newest)} (${ago(x.notes_newest)})`}>Hour by hour</SectionHead>
        {!x.hours.length && <State>Nothing for {date} yet: no Huginn flight and no reading.</State>}
        <div className="space-y-6">
          {x.hours.map(h => (
            <div key={h.hour} className="grid gap-4 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
              <section className="min-w-0 rounded-2xl border border-line bg-panel p-6">
                <div className="mb-3 flex items-baseline gap-3"><span className="font-mono text-2xl font-extrabold text-text">{h.hour}:00</span><Lbl>Huginn</Lbl></div>
                {h.huginn ? <Flight n={h.huginn} /> : <p className="m-0 text-sm text-muted">Huginn didn't fly this hour.</p>}
              </section>
              <section className="min-w-0 rounded-2xl border border-line bg-panel p-6">
                <div className="mb-3"><Lbl>Models · {h.readings.length} reading{h.readings.length === 1 ? "" : "s"}</Lbl></div>
                {h.readings.length ? h.readings.map(r => <ReadingCard key={r.grain + r.start + r.model + r.deep} r={r} />)
                  : <p className="m-0 text-sm text-muted">No model has read this hour yet.</p>}
              </section>
            </div>))}
        </div>
        <Hint>GET /api/hours?date={date} · readings from {x.readings_files.join(", ") || "none"} · MCP relic_readings, relic_search with vault</Hint>
      </>}
    </>
  );
}
