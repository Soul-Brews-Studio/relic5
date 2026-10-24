// Family (Nat, 2026-10-24: "can we visualize the lineage chart? or team? or historical working team?"). Two views:
// Lineage, who budded from whom (GET /api/lineage: mother-oracle's newest lineage scan, pushed by relic5-push), drawn
// as a tree per founding oracle; and Team, which oracles worked when (GET /api/team: sessions started per repo per
// Bangkok day, from the hub's own session table) as a heatmap, with the pairs that worked on the same days.
import { useMemo, useState } from "react";
import { usePoll } from "../api";
import { num, repoColor } from "../format";
import { Search } from "../components/Icons";
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
        <path key={"l" + r.n.name} d={`M${(r.depth - 1) * W + 14} ${r.parentY * H + 18} V${r.y * H + 18} H${r.depth * W + 6}`} fill="none" stroke="rgb(255 255 255 / .19)" />
      ))}
      {rows.map(r => {
        const c = repoColor(r.n.name);
        return (
          <g key={r.n.name} transform={`translate(${r.depth * W + 8}, ${r.y * H + 18})`}>
            <title>{`${r.n.name}${r.n.repo ? ` · ${r.n.repo}` : ""}${r.n.date ? ` · born ${r.n.date}` : ""} · ${r.n.commits} commits${r.n.awakened ? " · awakened" : ""}`}</title>
            <circle r={r.n.awakened ? 6 : 4.5} fill={r.n.awakened ? c : "var(--bg)"} stroke={c} strokeWidth="2" />
            {hit(r.n) && <circle r="11" fill="none" stroke="#fff" strokeWidth="1.5" />}
            <text x="13" y="4.5" fontSize="13" fill={hit(r.n) ? "#fff" : "var(--soft)"} fontWeight={r.depth === 0 || hit(r.n) ? 700 : 500}>{r.n.name}</text>
            {r.n.date && <text x={13 + r.n.name.length * 7.4 + 8} y="4.5" fontSize="11" fill="var(--faint)" fontFamily="var(--font-mono, monospace)">{r.n.date.slice(2)}</text>}
          </g>
        );
      })}
    </svg>
  );
}

function LineageView() {
  const p = usePoll<Lineage>("/api/lineage", 0);
  const [q, setQ] = useState("");
  const [showSolo, setShowSolo] = useState(false);
  const { kids, byName, families, solo } = useMemo(() => {
    const nodes = p.data?.nodes ?? [];
    const byName = new Map(nodes.map(n => [n.name, n]));
    const kids = new Map<string, LNode[]>();
    for (const n of nodes) if (n.parent) kids.set(n.parent, [...(kids.get(n.parent) ?? []), n]);
    const size = (name: string): number => 1 + (kids.get(name) ?? []).reduce((s, c) => s + size(c.name), 0);
    const families = (p.data?.roots ?? []).map(r => ({ root: r, size: size(r) })).sort((a, b) => b.size - a.size);
    const solo = nodes.filter(n => !n.parent && !n.children);
    return { kids, byName, families, solo };
  }, [p.data]);
  if (p.error && !p.data) return <State error>{p.error}</State>;
  if (!p.data) return <Loading label="Reading the lineage" />;
  if (!p.data.nodes.length) return <State>No lineage on the hub yet. A machine that holds mother-oracle sends its newest lineage scan with each push (relic5-push), or run /oracle-lineage-scan --write there first.</State>;
  const w = q.toLowerCase().trim();
  const shown = w ? families.filter(f => { const has = (name: string): boolean => name.toLowerCase().includes(w) || (kids.get(name) ?? []).some(c => has(c.name)); return has(f.root); }) : families;
  const budded = p.data.nodes.filter(n => n.parent).length;
  return (
    <div className="rise">
      <div className="mb-5 grid grid-cols-2 gap-6 md:grid-cols-4">
        {([["oracles", p.data.nodes.length], ["budded", budded], ["families", families.length], ["on their own", solo.length]] as const).map(([l, n]) => (
          <div key={l}><div className="text-xs font-bold tracking-[0.14em] text-muted uppercase">{l}</div><div className="mt-1 text-2xl font-extrabold text-text tabular-nums">{num(n)}</div></div>))}
      </div>
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <label className="relative flex min-w-0 flex-1 items-center sm:max-w-md">
          <span className="pointer-events-none absolute left-3.5 text-muted"><Search size={16} /></span>
          <input type="search" value={q} onChange={e => setQ(e.target.value)} placeholder="Find an oracle in the families" aria-label="Find an oracle"
            className="h-11 w-full rounded-lg border border-line bg-panel pr-3 pl-10 text-sm text-text placeholder:text-faint hover:border-line-strong focus:border-accent" />
        </label>
        <span className="text-sm text-muted">filled dot: awakened · line: budded from · date: born</span>
        <span className="ml-auto text-xs text-faint">lineage scan from {p.data.source}, newest birth {p.data.newest_birth}</span>
      </div>
      <div className="flex flex-col gap-4">
        {shown.map(f => (
          <section key={f.root} className="overflow-x-auto rounded-2xl border border-line bg-panel p-5">
            <div className="mb-2 flex items-baseline gap-3"><h2 className="m-0 text-base font-bold" style={{ color: repoColor(f.root) }}>{f.root}</h2><span className="text-sm text-muted">{f.size} in the family</span></div>
            <Tree root={f.root} kids={kids} byName={byName} q={w} />
          </section>
        ))}
      </div>
      <button type="button" onClick={() => setShowSolo(!showSolo)} className="mt-5 inline-flex min-h-11 items-center rounded-lg px-2 text-sm font-semibold text-accent">{showSolo ? "Hide" : "Show"} the {solo.length} oracles with no parent or child on record</button>
      {showSolo && <div className="mt-2 flex flex-wrap gap-2">{solo.filter(n => !w || n.name.toLowerCase().includes(w)).map(n => (
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
