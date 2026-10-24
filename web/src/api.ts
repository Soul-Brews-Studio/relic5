import { useCallback, useEffect, useRef, useState } from "react";

/** GET a hub route. The tailnet and loopback doors need no token; elsewhere /login?t=... sets the cookie once. */
export async function get<T>(path: string): Promise<T> {
  const r = await fetch(path, { credentials: "same-origin" });
  if (r.status === 401) throw new Error("no token: open /login?t=<your token> once");
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || String(r.status));
  return j as T;
}

export interface Polled<T> { data: T | null; error: string | null; at: Date | null; reload: () => void }

/** Poll a route every `every` ms while `on` (0 = once). Keeps the last good data when a poll fails. */
export function usePoll<T>(path: string | null, every = 0, on = true): Polled<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [at, setAt] = useState<Date | null>(null);
  const live = useRef(true);
  const load = useCallback(() => {
    if (!path) return;
    get<T>(path).then(d => { if (live.current) { setData(d); setError(null); setAt(new Date()); } })
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
