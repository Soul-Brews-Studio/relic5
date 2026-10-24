// Map (Nat, 2026-10-24: "vector 3d interactive visualization ... and 2d", "relic5 find vector i love": lanceglass's
// Session vector map, Atlas 3D + Flat 2D, and the old Studio's Planets). Every session with embedded messages is one
// point, placed by the mean of its vectors (GET /api/map, PCA to 3D on the hub), so sessions about the same thing sit
// together. Colour = repo. 3D (three.js, loaded only here) or 2D (a canvas); hover names a point, a click shows it on
// the right with "Read it" and "Search in it". The list under the map is the keyboard way to the same points.
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { usePoll } from "../api";
import { ago, bkk, num, repoColor } from "../format";
import { Search } from "../components/Icons";
import { Btn, cx, Lbl, Loading, PageHead, Seg, State } from "../components/ui";
import { shortRepo } from "./SearchView";

const Map3D = lazy(() => import("./Map3D"));

export interface MapPoint { sid: string; x: number; y: number; z: number; n: number; ts: string; repo?: string | null; name?: string | null; machines: string[] }
interface MapData { model: string; sessions: number; chunks: number; explained: number[]; projection: string; points: MapPoint[]; error?: string }

/** The 2D view: x and y of the same projection on a canvas; wheel zooms at the pointer, drag pans. */
function Map2D({ points, colors, dim, selected, onHover, onSelect }: {
  points: MapPoint[]; colors: string[]; dim: boolean[]; selected: number; onHover: (i: number, x: number, y: number) => void; onSelect: (i: number) => void;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const view = useRef({ k: 1, tx: 0, ty: 0 });
  const [, redraw] = useState(0);
  const scr = (p: MapPoint, w: number, h: number) => {
    const s = Math.min(w, h) * 0.45 * view.current.k;
    return [w / 2 + p.x * s + view.current.tx, h / 2 - p.y * s + view.current.ty];
  };
  useEffect(() => {
    const c = ref.current!, g = c.getContext("2d")!;
    const dpr = Math.min(devicePixelRatio, 2), w = c.clientWidth, h = c.clientHeight;
    c.width = w * dpr; c.height = h * dpr; g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    const order = points.map((_, i) => i).sort((a, b) => Number(!dim[b]) - Number(!dim[a]));   // dimmed first, lit on top
    for (const i of order) {
      const [x, y] = scr(points[i], w, h);
      g.globalAlpha = dim[i] ? 0.14 : 0.9;
      g.fillStyle = colors[i];
      g.beginPath(); g.arc(x, y, i === selected ? 6 : 3, 0, Math.PI * 2); g.fill();
    }
    if (selected >= 0) {
      const [x, y] = scr(points[selected], w, h);
      g.globalAlpha = 1; g.strokeStyle = "#ffffff"; g.lineWidth = 2; g.beginPath(); g.arc(x, y, 9, 0, Math.PI * 2); g.stroke();
    }
  });
  const nearest = (mx: number, my: number) => {
    const c = ref.current!, w = c.clientWidth, h = c.clientHeight;
    let best = -1, bd = 12 * 12;
    points.forEach((p, i) => { if (dim[i]) return; const [x, y] = scr(p, w, h); const d = (x - mx) ** 2 + (y - my) ** 2; if (d < bd) { bd = d; best = i; } });
    return best;
  };
  const drag = useRef<{ x: number; y: number; moved: boolean } | null>(null);
  return (
    <canvas ref={ref} className="absolute inset-0 h-full w-full cursor-grab touch-none" role="img" aria-label="Sessions in 2D: drag to pan, wheel to zoom"
      onWheel={e => {
        const r = ref.current!.getBoundingClientRect(), mx = e.clientX - r.left - r.width / 2, my = e.clientY - r.top - r.height / 2;
        const f = Math.exp(-e.deltaY * 0.0015), v = view.current, k = Math.min(40, Math.max(0.5, v.k * f)), q = k / v.k;
        v.tx = mx - (mx - v.tx) * q; v.ty = my - (my - v.ty) * q; v.k = k; redraw(n => n + 1);
      }}
      onPointerDown={e => { drag.current = { x: e.clientX, y: e.clientY, moved: false }; (e.target as HTMLElement).setPointerCapture(e.pointerId); }}
      onPointerMove={e => {
        const r = ref.current!.getBoundingClientRect();
        if (drag.current && (e.buttons & 1)) {
          const dx = e.clientX - drag.current.x, dy = e.clientY - drag.current.y;
          if (Math.abs(dx) + Math.abs(dy) > 2) drag.current.moved = true;
          view.current.tx += dx; view.current.ty += dy; drag.current.x = e.clientX; drag.current.y = e.clientY; redraw(n => n + 1);
          return;
        }
        onHover(nearest(e.clientX - r.left, e.clientY - r.top), e.clientX - r.left, e.clientY - r.top);
      }}
      onPointerUp={e => {
        const r = ref.current!.getBoundingClientRect();
        if (drag.current && !drag.current.moved) { const i = nearest(e.clientX - r.left, e.clientY - r.top); if (i >= 0) onSelect(i); }
        drag.current = null;
      }}
      onPointerLeave={() => onHover(-1, 0, 0)}
      onDoubleClick={() => { view.current = { k: 1, tx: 0, ty: 0 }; redraw(n => n + 1); }} />
  );
}

export function MapView({ openSession, search }: { openSession: (sid: string, name: string, repo: string) => void; search: (q: string, session?: string) => void }) {
  const [limit, setLimit] = useState("3000");
  const p = usePoll<MapData>(`/api/map?limit=${limit}`, 0);
  const [mode, setMode] = useState<"3d" | "2d">(() => (localStorage.getItem("relic5-map") as "3d" | "2d") || "3d");
  const [q, setQ] = useState("");
  const [repo, setRepo] = useState("");
  const [sel, setSel] = useState(-1);
  const [hover, setHover] = useState<{ i: number; x: number; y: number }>({ i: -1, x: 0, y: 0 });
  const [spin, setSpin] = useState(!matchMedia("(prefers-reduced-motion: reduce)").matches);
  const pts = p.data?.points ?? [];

  const colors = useMemo(() => pts.map(x => repoColor(shortRepo(x.repo))), [pts]);
  const repos = useMemo(() => {
    const m = new Map<string, number>();
    for (const x of pts) m.set(shortRepo(x.repo), (m.get(shortRepo(x.repo)) ?? 0) + 1);
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [pts]);
  const dim = useMemo(() => {
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    return pts.map(x => (!!repo && shortRepo(x.repo) !== repo) || (words.length > 0 && !words.every(w => `${x.name ?? ""} ${x.repo ?? ""} ${x.sid}`.toLowerCase().includes(w))));
  }, [pts, q, repo]);
  const lit = dim.filter(d => !d).length;
  const s = sel >= 0 ? pts[sel] : undefined;
  const hv = hover.i >= 0 ? pts[hover.i] : undefined;
  useEffect(() => { setSel(-1); }, [p.data]);

  if (p.error && !p.data) return <State error>{p.error}</State>;
  if (!p.data) return <><PageHead title="Map" sub="Every session placed by what it is about." /><Loading label="Placing the sessions (the first call builds the map on the hub)" /></>;
  if (p.data.error) return <State error>{p.data.error}</State>;
  const props = { points: pts, colors, dim, selected: sel, onHover: (i: number, x: number, y: number) => setHover({ i, x, y }), onSelect: setSel };

  return (
    <>
      <PageHead title="Map" sub={<>{num(p.data.sessions)} sessions, each one point placed by the mean of its {num(p.data.chunks)} embedded messages. Close points talk about the same things. Colour is the repo.</>}>
        <Seg label="View" value={mode} onChange={v => { setMode(v); localStorage.setItem("relic5-map", v); }} options={[{ value: "3d", label: "3D" }, { value: "2d", label: "2D" }]} />
        <Seg label="How many" value={limit} onChange={setLimit} options={[{ value: "1000", label: "1k newest" }, { value: "3000", label: "3k" }, { value: "10000", label: "10k" }]} />
      </PageHead>

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <label className="relative flex min-w-0 flex-1 items-center sm:max-w-md">
          <span className="pointer-events-none absolute left-3.5 text-muted"><Search size={16} /></span>
          <input type="search" value={q} onChange={e => setQ(e.target.value)} placeholder="Light up sessions by name, repo or id" aria-label="Light up sessions"
            className="h-11 w-full rounded-lg border border-line bg-panel pr-3 pl-10 text-sm text-text placeholder:text-faint hover:border-line-strong focus:border-accent" />
        </label>
        <span className="text-sm text-muted tabular-nums">{lit === pts.length ? `${num(pts.length)} points` : `${num(lit)} of ${num(pts.length)} lit`}</span>
        {mode === "3d" && <label className="flex min-h-11 items-center gap-2 text-sm text-soft"><input type="checkbox" checked={spin} onChange={e => setSpin(e.target.checked)} className="accent-[var(--accent)]" />turn slowly</label>}
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="relative h-[min(72vh,820px)] min-h-[420px] overflow-hidden rounded-2xl border border-line bg-[radial-gradient(ellipse_at_center,var(--raised)_0%,var(--deep)_75%)]">
          {mode === "3d"
            ? <Suspense fallback={<div className="p-6"><Loading label="Loading the 3D view" /></div>}><Map3D {...props} spin={spin && sel < 0} /></Suspense>
            : <Map2D {...props} />}
          {hv && (
            <div className="pointer-events-none absolute z-10 max-w-[320px] rounded-xl border border-line-strong bg-panel px-3.5 py-2.5 text-sm shadow-[var(--shadow-pop)]"
              style={{ left: Math.min(hover.x + 14, 9999), top: hover.y + 14 }}>
              <div className="font-semibold text-text">{hv.name || hv.sid.slice(0, 8)}</div>
              <div className="mt-0.5 flex items-center gap-1.5 text-xs text-muted"><span className="size-2 rounded-full" style={{ background: colors[hover.i] }} />{shortRepo(hv.repo)} · {ago(hv.ts)} · {hv.n} messages</div>
            </div>
          )}
          <p className="pointer-events-none absolute bottom-3 left-4 m-0 font-mono text-xs text-faint">
            {p.data.projection} · {p.data.model} · axes explain {p.data.explained.map(e => Math.round(e * 100) + "%").join(" / ")} · {mode === "3d" ? "drag to turn · wheel to zoom · right-drag to pan" : "drag to pan · wheel to zoom · double-click to reset"}
          </p>
        </div>

        <aside className="flex min-w-0 flex-col gap-5">
          <div className="rounded-2xl border border-line bg-panel p-5">
            {s ? <>
              <Lbl>selected</Lbl>
              <h2 className="m-0 mt-2 text-base font-bold text-text">{s.name || s.sid.slice(0, 8)}</h2>
              <div className="mt-1.5 flex items-center gap-1.5 text-sm" style={{ color: colors[sel] }}><span className="size-2 rounded-full" style={{ background: colors[sel] }} />{shortRepo(s.repo)}</div>
              <dl className="m-0 mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
                <dt className="text-muted">Newest</dt><dd className="m-0 text-soft">{bkk(s.ts)} · {ago(s.ts)}</dd>
                <dt className="text-muted">Embedded</dt><dd className="m-0 text-soft">{num(s.n)} messages</dd>
                <dt className="text-muted">On</dt><dd className="m-0 text-soft">{s.machines.join(", ") || "—"}</dd>
                <dt className="text-muted">Id</dt><dd className="m-0 truncate font-mono text-xs text-faint">{s.sid}</dd>
              </dl>
              <div className="mt-4 flex flex-wrap gap-2">
                <Btn primary type="button" onClick={() => openSession(s.sid, s.name || s.sid.slice(0, 8), shortRepo(s.repo))}>Read it</Btn>
                <Btn type="button" onClick={() => search("", s.sid.slice(0, 8))}>Search in it</Btn>
                <Btn type="button" onClick={() => setRepo(repo === shortRepo(s.repo) ? "" : shortRepo(s.repo))}>{repo === shortRepo(s.repo) ? "All repos" : "Only this repo"}</Btn>
              </div>
            </> : <p className="m-0 text-sm text-muted">Hover a point to name it, click to pick it. Picked points can be read here or searched inside.</p>}
          </div>
          <div className="rounded-2xl border border-line bg-panel p-5">
            <div className="mb-3 flex items-center justify-between"><Lbl>repos</Lbl>{repo && <button type="button" onClick={() => setRepo("")} className="text-xs font-semibold text-accent">show all</button>}</div>
            <ul className="m-0 flex max-h-[44vh] list-none flex-col gap-0.5 overflow-y-auto p-0">
              {repos.slice(0, 40).map(([r, n]) => (
                <li key={r}><button type="button" aria-pressed={repo === r} onClick={() => setRepo(repo === r ? "" : r)}
                  className={cx("flex min-h-9 w-full items-center gap-2.5 rounded-lg px-2.5 text-left text-sm", repo === r ? "bg-accent-wash text-text" : "text-soft hover:bg-raised")}>
                  <span className="size-2 flex-none rounded-full" style={{ background: repoColor(r) }} />
                  <span className="min-w-0 flex-1 truncate">{r}</span><span className="font-mono text-xs text-muted">{n}</span>
                </button></li>
              ))}
            </ul>
          </div>
        </aside>
      </div>
    </>
  );
}
