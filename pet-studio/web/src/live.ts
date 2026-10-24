// The page's half of the live link (server/index.ts "live"): SSE in, what the page has out.
// The agent (MCP) sets blocks or code, asks for a simulation or a tap; the page answers with its
// blocks, its simulator state and a picture of the simulator screen.
import { useEffect, useState } from "react";
import { currentView, simulate, snapshot, tap, simApp } from "./simstore";

export const ORIGIN = Math.random().toString(36).slice(2);
export type LiveEvent = { type: string; origin?: string; [k: string]: any };
const handlers = new Set<(e: LiveEvent) => void>();
let connected = false;
const status = new Set<(c: boolean) => void>();

/** Actions this page runs for the agent (studio v2): POST /api/live/call reaches them. */
let actions: Record<string, (args: any) => Promise<unknown> | unknown> = {};
export function setActions(a: typeof actions) { actions = a; }
let helloCanvas: string | null = null;
/** Say which canvas this page shows; repeated on every reconnect, so a server restart does not
 * leave the page unreachable for agents' calls. */
export function helloDesigner(canvas = "main") { helloCanvas = canvas; post("/api/live/hello", { role: "designer", canvas }); }

export function onLive(f: (e: LiveEvent) => void) { handlers.add(f); return () => { handlers.delete(f); }; }
export function useLiveConnected() {
  const [c, setC] = useState(connected);
  useEffect(() => { status.add(setC); return () => { status.delete(setC); }; }, []);
  return c;
}

const post = (path: string, body: object) =>
  fetch(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ ...body, origin: ORIGIN }) })
    .then((r) => r.json()).catch(() => null);
export const sendBlocks = (name: string, blocks: object) => post("/api/live/blocks", { name, blocks });
export const sendCode = (name: string, lang: string, source: string) => post("/api/live/code", { name, lang, source });

export function startLive() {
  // a WebSocket, not SSE: a stream would hold one of the browser's six connections to this host
  const onEvent = (data: string) => {
    const e: LiveEvent = JSON.parse(data);
    if (e.type === "call") {
      if (e.to !== ORIGIN) return;                         // addressed to another page
      const f = actions[e.action];
      Promise.resolve().then(async () => {
        if (!f) throw new Error(`no action ${e.action}; the page knows ${Object.keys(actions).join(", ")}`);
        (window as any).__agentCall = e.id;                   // changes made now are the agent's
        (window as any).__agentName = e.by ?? "agent";
        // cleared at once: a timer is throttled in a background tab and marked the person's next edit "agent".
        // Actions finish their own events before returning (drag waits for its pointerup).
        try { return await f(e.args ?? {}); }
        finally { if ((window as any).__agentCall === e.id) (window as any).__agentCall = null; }
      })
        .then((result) => post("/api/live/result", { id: e.id, ok: true, result: result ?? null }))
        .catch((err) => post("/api/live/result", { id: e.id, ok: false, error: String(err?.message ?? err) }));
      return;
    }
    if (e.origin === ORIGIN) return;                       // our own change coming back
    if (e.type === "simulate") simulate(String(e.name), e.pack).catch(() => {});
    if (e.type === "built" && e.simulate) simulate(String(e.name)).catch(() => {});
    if (e.type === "tap") tap(Number(e.x) || 0, Number(e.y) || 0);
    handlers.forEach((f) => f(e));
  };
  const connect = () => {
    const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/live/ws?origin=${ORIGIN}`);
    ws.onopen = () => {
      connected = true; status.forEach((f) => f(true));
      if (helloCanvas) post("/api/live/hello", { role: "designer", canvas: helloCanvas });
    };
    ws.onmessage = (m) => onEvent(String(m.data));
    ws.onclose = () => { connected = false; status.forEach((f) => f(false)); setTimeout(connect, 1000); };
  };
  connect();
  // the simulator screen and state, for the agent: twice a second while something runs
  let last = "";
  setInterval(() => {
    const png = snapshot();
    if (!png || png === last) return;
    last = png;
    post("/api/live/screen", { png });
    const cv = currentView();
    const v = cv && { app: simApp(), pack: cv.pack, state: ["idle", "busy", "attention", "sleep"][cv.state],
      heart: cv.heartUntil > performance.now(), caption: cv.caption, status: cv.status, log: cv.log.slice(-8) };
    post("/api/live/sim", { view: v });
  }, 500);
}
