import { useCallback, useEffect, useRef, useState } from "react";
import { report } from "./report";

/** Waits between tries when the hub does not answer at all: a deploy restarts it for some seconds (Nat, 2026-10-26:
 *  "when click sometimes this ... ERR_CONNECTION_REFUSED"). About 30 s in all, then the error is shown and reported. */
const RETRY = [1000, 2000, 4000, 8000, 15000];
const sleep = (ms: number) => new Promise(r => setTimeout(r, ms));

/** GET a hub route. The tailnet and loopback doors need no token; elsewhere /login?t=... sets the cookie once. */
export async function get<T>(path: string): Promise<T> {
  for (let i = 0; ; i++) {
    let r: Response;
    try {
      r = await fetch(path, { credentials: "same-origin" });
    } catch (e) {
      if (i < RETRY.length) { await sleep(RETRY[i]); continue; }
      report("fetch", `${path.split("?")[0]}: ${(e as Error).message}`);
      throw new Error("the hub is not answering (restarting?), tried for 30 s");
    }
    if (r.status === 401) throw new Error("no token: open /login?t=<your token> once");
    if (r.status === 502 || r.status === 503) { if (i < RETRY.length) { await sleep(RETRY[i]); continue; } }
    const j = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
    if (!r.ok) {
      if (r.status >= 500) report("http", `${path.split("?")[0]}: ${r.status} ${j.error ?? ""}`.trim());
      throw new Error(j.error || String(r.status));
    }
    return j as T;
  }
}

export interface Polled<T> { data: T | null; error: string | null; at: Date | null; reload: () => void }

/** The last answer of every route this page has read: a view that opens again shows it at once, then refreshes
 *  (Nat, 2026-10-25: "map page is slow can we have like animation and cache?"). Memory only, gone on reload. */
const LAST = new Map<string, { data: unknown; at: Date }>();

/** Read a route ahead of time into the cache, when the browser is idle (the Map's 0.7 MB of points, so its first
 *  open draws at once). */
export function prefetch(path: string) {
  if (LAST.has(path)) return;
  get(path).then(d => LAST.set(path, { data: d, at: new Date() })).catch(() => {});
}

/** Poll a route every `every` ms while `on` (0 = once). Keeps the last good data when a poll fails. */
export function usePoll<T>(path: string | null, every = 0, on = true): Polled<T> {
  const [data, setData] = useState<T | null>(() => (path ? (LAST.get(path)?.data as T | undefined) ?? null : null));
  const [error, setError] = useState<string | null>(null);
  const [at, setAt] = useState<Date | null>(null);
  const live = useRef(true);
  const load = useCallback(() => {
    if (!path) return;
    get<T>(path).then(d => { LAST.set(path, { data: d, at: new Date() }); if (live.current) { setData(d); setError(null); setAt(new Date()); } })
      .catch(e => { if (live.current) setError(String(e.message ?? e)); });
  }, [path]);
  useEffect(() => {
    live.current = true;
    if (!on) return () => { live.current = false; };
    load();
    const tick = () => { if (!document.hidden) load(); };   // a background tab polls nothing (36 KB per /api/tail)
    const t = every ? setInterval(tick, every) : undefined;
    const vis = () => { if (!document.hidden && every) load(); };
    document.addEventListener("visibilitychange", vis);
    return () => { live.current = false; if (t) clearInterval(t); document.removeEventListener("visibilitychange", vis); };
  }, [load, every, on]);
  return { data, error, at, reload: load };
}

/** POST a hub route that changes the hub's own records (saved searches): JSON with X-Relic5-Request, as Connect's tokens. */
export async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-Relic5-Request": "1" }, body: JSON.stringify(body) });
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || String(r.status));
  return j as T;
}

/** Call one of the hub's MCP tools from the page (the same tools agents use): -> its result, or throws its error. */
export async function tool<T>(name: string, args: Record<string, unknown>): Promise<T> {
  const r = await fetch("/mcp", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name, arguments: args } }) });
  const j = await r.json();
  const res = j.result ?? {};
  const text = res.content?.[0]?.text ?? "";
  if (res.isError || j.error) throw new Error(j.error?.message ?? text);
  return JSON.parse(text) as T;
}
