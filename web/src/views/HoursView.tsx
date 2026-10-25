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
