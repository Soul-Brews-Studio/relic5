// How the hub read this search, kept to one line (Nat, 2026-10-25: "can we show like how we tokenize?", then "too
// much? can we like 3d embedding? and result?"): the query as the BM25 index's tokens (GET /api/explain), each chip
// shaded by its weight (rarer = stronger, numbers on hover), and a 3D view of the hits in the Map's own embedding space
// over the dimmed cloud of sessions (POST /api/place). Click a hit in 3D to read it.
import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { compact, num } from "../format";
import type { Explain, Hit } from "../types";
import type { MapPoint } from "../views/MapView";
import { Loading, tokenHue } from "./ui";

const Map3D = lazy(() => import("../views/Map3D"));

interface Space { points: { uid: string; x: number; y: number; z: number }[]; centre: { x: number; y: number; z: number } | null; missing: string[];
  cloud: { sid: string; x: number; y: number; z: number; repo?: string | null }[]; error?: string }

function HitSpace({ hits, active, pick }: { hits: Hit[]; active: number; pick: (i: number) => void }) {
  const [sp, setSp] = useState<Space | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [hover, setHover] = useState<{ i: number; x: number; y: number }>({ i: -1, x: 0, y: 0 });
  const key = hits.map(h => h.uid).join(",");
  useEffect(() => {
    let live = true;
    setSp(null); setErr(null);
    fetch("/api/place", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ uids: hits.map(h => h.uid), scores: hits.map(h => h.score) }) })
      .then(r => r.json()).then(j => { if (live) (j.error ? setErr(j.error) : setSp(j)); }).catch(e => live && setErr(String(e)));
    return () => { live = false; };
  }, [key]);   // eslint-disable-line
  // points: the cloud first (dimmed), then the hits in rank order, then the hits' centre
  const view = useMemo(() => {
    if (!sp) return null;
    const at = new Map(sp.points.map(p => [p.uid, p]));
    const hitIdx = hits.map((h, i) => ({ h, i, p: at.get(h.uid) })).filter(x => x.p);
    const pts: MapPoint[] = [
      ...sp.cloud.map(c => ({ sid: c.sid, x: c.x, y: c.y, z: c.z, n: 0, ts: "", repo: c.repo, machines: [] })),
      ...hitIdx.map(x => ({ sid: x.h.session_uuid, x: x.p!.x, y: x.p!.y, z: x.p!.z, n: 0, ts: x.h.ts, repo: x.h.repo_key, name: x.h.session_name, machines: x.h.machines })),
      ...(sp.centre ? [{ sid: "centre", ...sp.centre, n: 0, ts: "", machines: [] }] : []),
    ];
    const nc = sp.cloud.length;
    const colors = pts.map((_, i) => (i < nc ? "#6b7488" : i < nc + hitIdx.length ? "#64b5f6" : "#f5b73b"));
    const dim = pts.map((_, i) => i < nc);
    return { pts, colors, dim, nc, hitIdx };
  }, [sp, key]);   // eslint-disable-line
  if (err) return <p className="m-0 px-4 py-3 text-sm text-muted">The 3D view needs vectors: {err}</p>;
  if (!view) return <div className="p-4"><Loading label="Placing the hits" /></div>;
  const sel = view.hitIdx.findIndex(x => x.i === active);
  const hv = hover.i >= view.nc && hover.i < view.nc + view.hitIdx.length ? view.hitIdx[hover.i - view.nc] : null;
  return (
    <div>
      <div className="relative h-[340px] overflow-hidden rounded-lg bg-deep" onPointerLeave={() => setHover({ i: -1, x: 0, y: 0 })}>
        <Suspense fallback={<div className="p-4"><Loading label="Loading the 3D view" /></div>}>
          <Map3D points={view.pts} colors={view.colors} dim={view.dim} selected={sel >= 0 ? view.nc + sel : -1} spin={false}
            onHover={(i, x, y) => setHover({ i, x, y })} onSelect={i => { const x = view.hitIdx[i - view.nc]; if (x) pick(x.i); }} />
        </Suspense>
        {hv && <div className="pointer-events-none absolute z-[2] max-w-72 rounded-lg border border-line bg-panel px-3 py-2 text-xs shadow-[var(--shadow-pop)]" style={{ left: hover.x + 12, top: hover.y + 12 }}>
          <b className="text-text">#{hv.i + 1}</b> <span className="text-soft">{hv.h.session_name ?? hv.h.session_uuid.slice(0, 8)}</span>
          <span className="block text-muted">score {hv.h.score.toFixed(2)} · {hv.h.role}</span></div>}
      </div>
      <p className="m-0 mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
        <span className="inline-flex items-center gap-1.5"><i className="size-2 rounded-full bg-accent" />a hit, placed by its own embedding</span>
        <span className="inline-flex items-center gap-1.5"><i className="size-2 rounded-full bg-amber" />where the hits sit, by score (the hub does not embed the query)</span>
        <span className="inline-flex items-center gap-1.5"><i className="size-2 rounded-full bg-faint" />every session, as on the Map</span>
        {sp && sp.missing.length > 0 && <span>{sp.missing.length} hits have no vector yet</span>}
        <span className="ml-auto">drag to turn · wheel to zoom · click a hit to read it</span>
      </p>
    </div>
  );
}

export function SearchExplain({ e, hits, active, pick }: { e: Explain; hits: Hit[]; active: number; pick: (i: number) => void }) {
  const [open3d, setOpen3d] = useState(() => localStorage.getItem("relic5-3d") === "1");
  const toggle = () => { localStorage.setItem("relic5-3d", open3d ? "0" : "1"); setOpen3d(!open3d); };
  const top = Math.max(0.001, ...e.terms.map(t => t.idf ?? 0));
  return (
    <section aria-label="How this search reads" className="mx-5 mb-4">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5 text-xs text-muted">
        <span>read as</span>
        {e.terms.map((t, i) => {
          const w = (t.idf ?? 0) / top;
          return (
            <span key={t.token} title={`${t.token}: in ${num(t.rows)} of ${num(e.rows)} rows · weight ${t.idf ?? "?"} (rarer counts more)`}
              className="rounded-md px-1.5 py-0.5 font-mono" style={{ background: `color-mix(in srgb, ${tokenHue(i)} ${Math.round(10 + 40 * w)}%, transparent)`, color: "var(--text)", boxShadow: `inset 0 -2px 0 ${tokenHue(i)}` }}>
              {t.token}<span className="ml-1 text-faint">{compact(t.rows)}</span></span>
          );
        })}
        {e.phrase_rows != null && e.tokens.length > 1 && <span>· exact phrase in {num(e.phrase_rows)}</span>}
        <button type="button" onClick={toggle} aria-pressed={open3d}
          className="ml-auto inline-flex min-h-9 items-center rounded-lg px-2 font-semibold text-accent hover:bg-raised">{open3d ? "Hide 3D" : "See the hits in 3D"}</button>
      </div>
      {open3d && hits.length > 0 && <div className="mt-3"><HitSpace hits={hits.slice(0, 40)} active={active} pick={pick} /></div>}
    </section>
  );
}
