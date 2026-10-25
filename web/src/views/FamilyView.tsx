// Family (Nat, 2026-10-24: "can we visualize the lineage chart? or team? or historical working team?"). Two views:
// Lineage, who budded from whom (GET /api/lineage: mother-oracle's newest lineage scan, pushed by relic5-push), drawn
// as a tree per founding oracle; and Team, which oracles worked when (GET /api/team: sessions started per repo per
// Bangkok day, from the hub's own session table) as a heatmap, with the pairs that worked on the same days.
import { useMemo, useState } from "react";
import { usePoll } from "../api";
import { num, repoColor } from "../format";
import { Chevron, Search } from "../components/Icons";
import { cx, Lbl, Loading, PageHead, Seg, State } from "../components/ui";

interface LNode { name: string; repo?: string; org?: string; parent: string | null; parent_named?: string | null; origin?: string; date?: string; awakened: boolean; commits: number; children: number }
interface Lineage { source: string | null; newest_birth: string | null; pushed?: string; nodes: LNode[]; roots: string[] }
interface Team { window_days: number; days: string[]; repos: { repo: string; sessions: number; by_day: Record<string, number> }[]; pairs: { a: string; b: string; days: number }[] }

/** One founder's family as a tidy tree in SVG: depth to the right, one row per oracle in birth order. */
function Tree({ root, kids, byName, q }: { root: string; kids: Map<string, LNode[]>; byName: Map<string, LNode>; q: string }) {
  const rows: { n: LNode; depth: number; y: number; parentY: number | null }[] = [];
  const walk = (name: string, depth: number, parentY: number | null) => {
    const n = byName.get(name);
    if (!n) return;
    const y = rows.length;
    rows.push({ n, depth, y, parentY });
    for (const c of (kids.get(name) ?? []).slice().sort((a, b) => (a.date ?? "").localeCompare(b.date ?? ""))) walk(c.name, depth + 1, y);
  };
  walk(root, 0, null);
  const H = 30, W = 210, maxD = Math.max(...rows.map(r => r.depth));
  const hit = (n: LNode) => !!q && n.name.toLowerCase().includes(q);
  return (
    <svg width={(maxD + 1) * W + 160} height={rows.length * H + 12} role="img" aria-label={`${root}'s family: ${rows.length} oracles`} className="block">
      {rows.map(r => r.parentY != null && (
        <path key={"l" + r.n.name} d={`M${(r.depth - 1) * W + 14} ${r.parentY * H + 18} V${r.y * H + 18} H${r.depth * W + 6}`} fill="none" stroke="var(--line-strong)" />
      ))}
      {rows.map(r => {
        const c = repoColor(r.n.name);
        return (
          <g key={r.n.name} transform={`translate(${r.depth * W + 8}, ${r.y * H + 18})`}>
            <title>{`${r.n.name}${r.n.repo ? ` · ${r.n.repo}` : ""}${r.n.date ? ` · born ${r.n.date}` : ""} · ${r.n.commits} commits${r.n.awakened ? " · awakened" : ""}`}</title>
            <circle r={r.n.awakened ? 6 : 4.5} fill={r.n.awakened ? c : "var(--bg)"} stroke={c} strokeWidth="2" />
            {hit(r.n) && <circle r="11" fill="none" stroke="var(--text)" strokeWidth="1.5" />}
            <text x="13" y="4.5" fontSize="13" fill={hit(r.n) ? "var(--text)" : "var(--soft)"} fontWeight={r.depth === 0 || hit(r.n) ? 700 : 500}>{r.n.name}</text>
            {r.n.date && <text x={13 + r.n.name.length * 7.4 + 8} y="4.5" fontSize="11" fill="var(--faint)" fontFamily="var(--font-mono, monospace)">{r.n.date.slice(2)}</text>}
          </g>
        );
      })}
    </svg>
  );
}

const MONTH = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const mlabel = (m: string) => (m === "earlier" ? "earlier" : `${MONTH[+m.slice(5, 7)]} '${m.slice(2, 4)}`);

/** Births per month from the lineage scan's dates: the months from the first one with 3 or more births to the newest,
 *  every month in between kept (a month with none is a gap, not skipped); births before that go in "earlier". */
function births(nodes: LNode[]) {
  const by = new Map<string, { budded: number; standalone: number }>();
  for (const n of nodes) {
    if (!n.date) continue;
    const m = n.date.slice(0, 7), v = by.get(m) ?? { budded: 0, standalone: 0 };
    if (n.parent) v.budded++; else v.standalone++;
    by.set(m, v);
  }
  const ks = [...by.keys()].sort(), start = ks.find(k => (by.get(k)!.budded + by.get(k)!.standalone) >= 3) ?? ks[0];
  if (!start) return [];
  const out: { m: string; budded: number; standalone: number; total: number }[] = [];
  const early = ks.filter(k => k < start).reduce((a, k) => ({ budded: a.budded + by.get(k)!.budded, standalone: a.standalone + by.get(k)!.standalone }), { budded: 0, standalone: 0 });
  if (early.budded + early.standalone) out.push({ m: "earlier", ...early, total: 0 });
  for (let [y, mo] = [+start.slice(0, 4), +start.slice(5, 7)]; `${y}-${String(mo).padStart(2, "0")}` <= ks[ks.length - 1]; mo === 12 ? (y++, mo = 1) : mo++) {
    const k = `${y}-${String(mo).padStart(2, "0")}`;
    out.push({ m: k, ...(by.get(k) ?? { budded: 0, standalone: 0 }), total: 0 });
  }
  let run = 0;
  for (const r of out) { run += r.budded + r.standalone; r.total = run; }
  return out;
}

function Growth({ rows, undated }: { rows: ReturnType<typeof births>; undated: number }) {
  const [hov, setHov] = useState(-1);
  const H = 150, n = rows.length, W = n * 20, top = Math.max(1, ...rows.map(r => r.budded + r.standalone)), all = rows[n - 1]?.total ?? 1;
  const r = rows[hov];
  const read = r ? `${mlabel(r.m)}: ${r.budded + r.standalone} born (${r.budded} budded, ${r.standalone} standalone) · ${r.total} by then` : null;
  const axis = (
    <div className="mt-1.5 flex justify-between font-mono text-xs text-faint"><span>{rows[0] ? mlabel(rows[0].m) : ""}</span><span>{rows[n - 1] ? mlabel(rows[n - 1].m) : ""}</span></div>
  );
  return (
    <section className="rounded-2xl border border-line bg-panel p-5" onMouseLeave={() => setHov(-1)}>
      <p className="m-0 mb-4 min-h-5 font-mono text-xs text-muted tabular-nums" aria-live="polite">{read ?? `hover a month · ${undated ? `${undated} oracles have no birth date and are left out` : "every oracle has a birth date"}`}</p>
      <div className="grid gap-8 lg:grid-cols-2">
        <figure className="m-0 min-w-0">
          <figcaption className="mb-2 flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm"><span className="font-bold text-text">The family, growing</span><span className="text-muted">every oracle born so far, month by month</span></figcaption>
          <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="block h-[150px] w-full" role="img" aria-label={`Oracles born so far, ${all} by ${rows[n - 1] ? mlabel(rows[n - 1].m) : ""}`}>
            <line x1="0" x2={W} y1={H - 0.5} y2={H - 0.5} stroke="var(--line-strong)" vectorEffect="non-scaling-stroke" />
            <polygon points={`10,${H} ${rows.map((x, i) => `${i * 20 + 10},${H - 4 - (x.total / all) * (H - 12)}`).join(" ")} ${W - 10},${H}`} fill="var(--accent-wash)" />
            <polyline points={rows.map((x, i) => `${i * 20 + 10},${H - 4 - (x.total / all) * (H - 12)}`).join(" ")} fill="none" stroke="var(--accent)" strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
            {hov >= 0 && <line x1={hov * 20 + 10} x2={hov * 20 + 10} y1="0" y2={H} stroke="var(--line-strong)" vectorEffect="non-scaling-stroke" />}
            {rows.map((x, i) => <rect key={x.m} x={i * 20} y="0" width="20" height={H} fill="transparent" onMouseEnter={() => setHov(i)} />)}
          </svg>
          {axis}
        </figure>
        <figure className="m-0 min-w-0">
          <figcaption className="mb-2 flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm">
            <span className="font-bold text-text">Born each month</span>
            <span className="inline-flex items-center gap-1.5 text-muted"><i className="inline-block size-2.5 rounded-sm bg-amber" />budded from an oracle</span>
            <span className="inline-flex items-center gap-1.5 text-muted"><i className="inline-block size-2.5 rounded-sm bg-accent" />standalone</span>
          </figcaption>
          <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="block h-[150px] w-full" role="img" aria-label={`Births per month, most ${top} in one month`}>
            <line x1="0" x2={W} y1={H - 0.5} y2={H - 0.5} stroke="var(--line-strong)" vectorEffect="non-scaling-stroke" />
            {rows.map((x, i) => {
              const s = (x.standalone / top) * (H - 6), b = (x.budded / top) * (H - 6), dim = hov >= 0 && hov !== i ? 0.4 : 1;
              return (
                <g key={x.m} opacity={dim} onMouseEnter={() => setHov(i)}>
                  <rect x={i * 20} y="0" width="20" height={H} fill="transparent" />
                  {s > 0 && <rect x={i * 20 + 4} y={H - s} width="12" height={s} fill="var(--accent)" />}
                  {b > 0 && <rect x={i * 20 + 4} y={H - s - b} width="12" height={Math.max(0, b - (s ? 1.5 : 0))} rx="1.5" fill="var(--amber)" />}
                </g>
              );
            })}
          </svg>
          {axis}
        </figure>
      </div>
    </section>
  );
}

function LineageView() {
  const p = usePoll<Lineage>("/api/lineage", 0);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [showSolo, setShowSolo] = useState(false);
  const d = useMemo(() => {
    const nodes = p.data?.nodes ?? [];
    const byName = new Map(nodes.map(n => [n.name, n]));
    const kids = new Map<string, LNode[]>();
    for (const n of nodes) if (n.parent) kids.set(n.parent, [...(kids.get(n.parent) ?? []), n]);
    const members = (name: string, depth = 0, out: { n: LNode; depth: number }[] = []) => {
      const n = byName.get(name);
      if (n) { out.push({ n, depth }); for (const c of kids.get(name) ?? []) members(c.name, depth + 1, out); }
      return out;
    };
    const families = (p.data?.roots ?? []).map(r => {
      const m = members(r), dates = m.map(x => x.n.date).filter(Boolean).sort() as string[];
      return { root: r, size: m.length, gens: Math.max(...m.map(x => x.depth)) + 1, awake: m.filter(x => x.n.awakened).length, first: dates[0], last: dates[dates.length - 1], dates, names: m.map(x => x.n.name) };
    }).sort((a, b) => b.size - a.size);
    const solo = nodes.filter(n => !n.parent && !n.children);
    const dated = nodes.filter(n => n.date).sort((a, b) => a.date!.localeCompare(b.date!));
    const rows = births(nodes);
    const busiest = rows.filter(r => r.m !== "earlier").reduce((a, r) => (r.budded + r.standalone > a.budded + a.standalone ? r : a), rows[0]);
    const firstBud = dated.find(n => n.parent);
    return { byName, kids, families, solo, dated, rows, busiest, firstBud, budded: nodes.filter(n => n.parent).length, awake: nodes.filter(n => n.awakened).length };
  }, [p.data]);
  if (p.error && !p.data) return <State error>{p.error}</State>;
  if (!p.data) return <Loading label="Reading the lineage" />;
  if (!p.data.nodes.length) return <State>No lineage on the hub yet. A machine that holds mother-oracle sends its newest lineage scan with each push (relic5-push), or run /oracle-lineage-scan --write there first.</State>;
  const w = q.toLowerCase().trim();
  const shown = w ? d.families.filter(f => f.names.some(x => x.toLowerCase().includes(w))) : d.families;
  const months = d.rows.map(r => r.m).filter(m => m !== "earlier"), m0 = months[0] ?? "", mN = months[months.length - 1] ?? "";
  const pos = (date: string) => { const i = months.indexOf(date.slice(0, 7)); return i < 0 ? (date.slice(0, 7) < m0 ? 0 : 100) : ((i + (+date.slice(8, 10) || 15) / 31) / Math.max(1, months.length)) * 100; };
  const nodes = p.data.nodes, first = d.dated[0];
  const marks = [
    first && { at: first.date!, head: "The oldest", what: `${first.name}, the first oracle with a birth date` },
    d.firstBud && { at: d.firstBud.date!, head: "The first bud", what: `${d.firstBud.name}, budded from ${d.firstBud.parent}` },
    d.busiest && { at: d.busiest.m + "-15", head: "The busiest month", what: `${d.busiest.budded + d.busiest.standalone} born, ${d.busiest.budded} of them budded`, month: true },
    p.data.newest_birth && { at: p.data.newest_birth, head: "The newest", what: `${d.dated[d.dated.length - 1]?.name ?? ""}` },
  ].filter(Boolean) as { at: string; head: string; what: string; month?: boolean }[];
  const toggle = (r: string) => setOpen(s => { const n = new Set(s); if (n.has(r)) n.delete(r); else n.add(r); return n; });
  return (
    <div className="rise">
      <p className="m-0 mb-8 max-w-[52ch] text-xl leading-snug font-semibold tracking-[-0.01em] text-soft text-balance">
        <span className="text-text tabular-nums">{num(nodes.length)}</span> oracles in <span className="text-text tabular-nums">{num(d.families.length)}</span> families.{" "}
        <span className="text-amber tabular-nums">{num(d.budded)}</span> budded from another oracle, <span className="text-text tabular-nums">{num(d.solo.length)}</span> stand on their own, and <span className="text-text tabular-nums">{num(d.awake)}</span> have been awakened.
      </p>

      {d.rows.length > 1 && <Growth rows={d.rows} undated={nodes.filter(n => !n.date).length} />}

      <ol className="m-0 mt-6 mb-12 grid list-none gap-x-6 gap-y-3 p-0 sm:grid-cols-2 xl:grid-cols-4">
        {marks.map(x => (
          <li key={x.what} className="border-t border-line-strong pt-3">
            <div className="flex items-baseline justify-between gap-3"><b className="text-sm text-text">{x.head}</b><time className="font-mono text-xs text-amber tabular-nums">{x.month ? mlabel(x.at.slice(0, 7)) : x.at}</time></div>
            <p className="m-0 mt-1 text-sm text-soft">{x.what}</p>
          </li>))}
      </ol>

      <div className="mb-4 flex flex-wrap items-end gap-x-6 gap-y-3">
        <div className="min-w-0 flex-1">
          <h2 className="m-0 text-lg font-bold tracking-[-0.01em] text-text">The families</h2>
          <p className="m-0 mt-1 text-sm text-muted">Each founder and everyone budded from it, biggest first. Ticks show when each one was born ({mlabel(m0)} to {mlabel(mN)}). Open a family to see its tree.</p>
        </div>
        <label className="relative flex w-full min-w-0 items-center sm:w-72">
          <span className="pointer-events-none absolute left-3.5 text-muted"><Search size={16} /></span>
          <input type="search" value={q} onChange={e => setQ(e.target.value)} placeholder="Find an oracle in the families" aria-label="Find an oracle"
            className="h-11 w-full rounded-lg border border-line bg-panel pr-3 pl-10 text-sm text-text placeholder:text-faint hover:border-line-strong focus:border-accent" />
        </label>
      </div>
      <div className="overflow-hidden rounded-2xl border border-line bg-panel">
        {shown.map(f => {
          const c = repoColor(f.root), isOpen = open.has(f.root) || (!!w && shown.length <= 3);
          return (
            <div key={f.root} className="border-b border-line last:border-b-0">
              <button type="button" aria-expanded={isOpen} onClick={() => toggle(f.root)}
                className="grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-x-5 gap-y-2 px-5 py-3.5 text-left transition-colors hover:bg-raised md:grid-cols-[minmax(0,12rem)_11rem_minmax(0,1fr)_1.5rem]">
                <span className="min-w-0">
                  <b className="block truncate text-base" style={{ color: c }}>{f.root}</b>
                  <span className="block text-xs text-muted">{f.first ? `${f.first.slice(2)} → ${f.last?.slice(2)}` : "no dates"}</span>
                </span>
                <span className="text-right text-sm text-soft md:text-left"><b className="text-text tabular-nums">{f.size}</b> {f.size === 1 ? "oracle" : "oracles"}<span className="block text-xs text-muted">{f.gens} {f.gens === 1 ? "generation" : "generations"} · {f.awake} awake</span></span>
                <span className="relative col-span-2 h-6 md:col-span-1" aria-hidden>
                  <span className="absolute inset-x-0 top-1/2 h-px bg-line" />
                  {f.dates.map((x, i) => <span key={i} className="absolute top-1 h-4 w-0.5 rounded-full" style={{ left: `${pos(x)}%`, background: c, opacity: 0.85 }} />)}
                </span>
                <span className={cx("hidden text-muted transition-transform duration-[120ms] md:block", isOpen && "rotate-90")} aria-hidden><Chevron size={18} /></span>
              </button>
              {isOpen && <div className="overflow-x-auto border-t border-line bg-deep px-5 py-4"><Tree root={f.root} kids={d.kids} byName={d.byName} q={w} /></div>}
            </div>
          );
        })}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
        <span>in a tree: filled dot = awakened · line = budded from · date = born</span>
        <span className="ml-auto font-mono text-faint">lineage scan from {p.data.source}, newest birth {p.data.newest_birth}</span>
      </div>
      <button type="button" onClick={() => setShowSolo(!showSolo)} className="mt-5 inline-flex min-h-11 items-center rounded-lg px-2 text-sm font-semibold text-accent">{showSolo ? "Hide" : "Show"} the {d.solo.length} oracles with no parent or child on record</button>
      {showSolo && <div className="mt-2 flex flex-wrap gap-2">{d.solo.filter(n => !w || n.name.toLowerCase().includes(w)).map(n => (
        <span key={n.name} title={`${n.repo ?? ""} · born ${n.date ?? "?"}`} className="rounded-lg border border-line bg-panel px-2.5 py-1 text-sm text-soft"><span className="mr-1.5 inline-block size-2 rounded-full" style={{ background: repoColor(n.name) }} />{n.name}</span>))}</div>}
    </div>
  );
}

function TeamView() {
  const [days, setDays] = useState("90");
  const p = usePoll<Team>(`/api/team?days=${days}`, 0);
  if (p.error && !p.data) return <State error>{p.error}</State>;
  if (!p.data) return <Loading label="Reading who worked when" />;
  const t = p.data, max = Math.max(1, ...t.repos.flatMap(r => Object.values(r.by_day)));
  const cell = (n: number) => (n ? `color-mix(in srgb, #4a98d8 ${Math.round(18 + 82 * Math.log1p(n) / Math.log1p(max))}%, transparent)` : "var(--raised)");
  return (
    <div className="rise">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Seg label="Window" value={days} onChange={setDays} options={[{ value: "30", label: "30 days" }, { value: "90", label: "90 days" }, { value: "180", label: "180 days" }, { value: "365", label: "a year" }]} />
        <span className="text-sm text-muted">sessions started per repo per day (Bangkok), the {t.repos.length} busiest repos · darker = more</span>
      </div>
      <section className="overflow-x-auto rounded-2xl border border-line bg-panel p-5">
        <table className="border-collapse text-xs">
          <thead><tr><th className="sticky left-0 bg-panel" />{t.days.map((d, i) => <th key={d} className="h-14 w-3 p-0 align-bottom font-normal text-faint">{(i === 0 || d.endsWith("-01") || d.endsWith("-15")) && <span className="block w-3 origin-bottom-left translate-x-1.5 -rotate-90 whitespace-nowrap font-mono">{d.slice(5)}</span>}</th>)}<th /></tr></thead>
          <tbody>{t.repos.map(r => (
            <tr key={r.repo}>
              <td className="sticky left-0 z-[1] max-w-[260px] truncate bg-panel py-0.5 pr-3 text-sm text-soft" title={r.repo}><span className="mr-2 inline-block size-2 rounded-full" style={{ background: repoColor(r.repo) }} />{r.repo}</td>
              {t.days.map(d => <td key={d} className="p-[1.5px]"><div className="size-3 rounded-[3px]" title={`${r.repo} · ${d}: ${r.by_day[d] ?? 0} sessions`} style={{ background: cell(r.by_day[d] ?? 0) }} /></td>)}
              <td className="pl-3 text-right font-mono text-muted tabular-nums">{num(r.sessions)}</td>
            </tr>
          ))}</tbody>
        </table>
      </section>
      <section className="mt-5 rounded-2xl border border-line bg-panel p-5">
        <h2 className="m-0 text-base font-bold text-text">Who worked together</h2>
        <p className="m-0 mt-1 mb-4 text-sm text-muted">Pairs of repos with sessions on the same days, most shared days first: the fleet's working teams in this window.</p>
        <div className="grid gap-x-8 gap-y-1 md:grid-cols-2">{t.pairs.slice(0, 24).map(x => (
          <div key={x.a + x.b} className="flex items-center gap-2 py-1 text-sm">
            <span className="min-w-0 flex-1 truncate text-soft"><span style={{ color: repoColor(x.a) }}>{x.a}</span> <span className="text-faint">+</span> <span style={{ color: repoColor(x.b) }}>{x.b}</span></span>
            <span className="h-1.5 w-24 rounded-full bg-raised"><span className="block h-1.5 rounded-full bg-accent" style={{ width: `${(100 * x.days) / (t.pairs[0]?.days || 1)}%` }} /></span>
            <span className="w-14 text-right font-mono text-xs text-muted">{x.days} days</span>
          </div>))}</div>
      </section>
    </div>
  );
}

export function FamilyView() {
  const [mode, setMode] = useState<"lineage" | "team">("lineage");
  return (
    <>
      <PageHead title="Family" sub="The fleet as a family, who budded from whom, and as a team, which oracles worked when and alongside whom.">
        <Seg label="View" value={mode} onChange={setMode} options={[{ value: "lineage", label: "Lineage" }, { value: "team", label: "Working team" }]} />
      </PageHead>
      {mode === "lineage" ? <LineageView /> : <TeamView />}
      <div className={cx("mt-8")}><Lbl>source</Lbl> <span className="font-mono text-xs text-faint">GET /api/lineage (mother-oracle lineage scan) · /api/team (meta/sessions.parquet)</span></div>
    </>
  );
}
