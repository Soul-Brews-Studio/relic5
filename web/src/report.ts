// The page reports its own errors to the hub, a Sentry of our own (Nat, 2026-10-26: "we should register like sentry?").
// Nothing leaves the hub: reports queue in localStorage while the hub cannot be reached (a deploy restarts it) and go to
// POST /api/client-error when it answers again; the Incidents page lists them (pageerrors.py).

const KEY = "relic5-page-errors";
const build = (document.querySelector('script[type="module"][src*="/assets/"]') as HTMLScriptElement | null)?.src.split("/").pop() ?? "";

interface Report { kind: string; message: string; stack?: string; url: string; view: string; ua: string; at: string; build: string; count: number }

const read = (): Report[] => { try { return JSON.parse(localStorage.getItem(KEY) || "[]"); } catch { return []; } };
const write = (q: Report[]) => { try { localStorage.setItem(KEY, JSON.stringify(q.slice(-50))); } catch { /* storage full: drop */ } };

/** Queue one error; the same kind + message only counts up. */
export function report(kind: string, message: string, stack?: string) {
  const q = read();
  const view = new URLSearchParams(location.hash.slice(1)).get("tab") ?? "home";
  const same = q.find(r => r.kind === kind && r.message === message && r.view === view);
  if (same) { same.count += 1; same.at = new Date().toISOString(); }
  else q.push({ kind, message: message.slice(0, 500), stack: stack?.slice(0, 2000), url: location.href.slice(0, 300), view,
                ua: navigator.userAgent.slice(0, 200), at: new Date().toISOString(), build, count: 1 });
  write(q);
  setTimeout(flush, 1500);
}

let flushing = false;
/** Send the queue; it stays queued when the hub does not take it. */
export async function flush() {
  if (flushing) return;
  const q = read();
  if (!q.length) return;
  flushing = true;
  try {
    const r = await fetch("/api/client-error", { method: "POST", credentials: "same-origin", keepalive: true,
      headers: { "Content-Type": "application/json", "X-Relic5-Request": "1" }, body: JSON.stringify(q) });
    if (r.ok) write(read().slice(q.length));
  } catch { /* the hub is away: keep them */ }
  flushing = false;
}

const sleep = (ms: number) => new Promise(r => setTimeout(r, ms));

/** A code chunk would not load: after a deploy the page still asks for the old build's file names, or the hub is
 *  restarting. Wait until the hub answers, then reload once into the new build (not twice inside a minute). */
async function reloadWhenBack(why: string) {
  report("chunk", why);
  const last = Number(sessionStorage.getItem("relic5-reloaded-at") || 0);
  if (Date.now() - last < 60_000) return;
  for (let i = 0; i < 60; i++) {
    try { if ((await fetch("/health", { cache: "no-store", credentials: "same-origin" })).ok) break; } catch { /* still down */ }
    await sleep(2000);
  }
  sessionStorage.setItem("relic5-reloaded-at", String(Date.now()));
  location.reload();
}

export function install() {
  window.addEventListener("error", e => {
    if (e.message) report("error", e.message, (e.error as Error | undefined)?.stack);
  });
  window.addEventListener("unhandledrejection", e => {
    const err = e.reason as Error | undefined;
    const msg = String(err?.message ?? e.reason ?? "");
    if (/dynamically imported module|Importing a module script failed|error loading dynamically/i.test(msg)) { e.preventDefault(); void reloadWhenBack(msg); return; }
    report("rejection", msg, err?.stack);
  });
  window.addEventListener("vite:preloadError", e => { e.preventDefault(); void reloadWhenBack(String((e as Event & { payload?: Error }).payload?.message ?? "chunk failed to load")); });
  window.addEventListener("online", () => void flush());
  setInterval(() => void flush(), 60_000);
  void flush();
}
