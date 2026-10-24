// The designer page as an agent sees and drives it, after droidread's MCP (nat-build-with-oracle/
// droidread): focus (what is open), snapshot (a tree with [ref=eN] handles, the one you act on),
// query (find by selector), screenshot, tap (a ref, a selector, or a point on the artboard),
// drag (a real pointer path: the current tool draws, moves or sizes), type, key, and since (every
// change, by the person or the agent, after a cursor).
//
// Taps and drags on the artboard are synthetic pointer events on fabric's upper canvas, so they
// go through the same tool code a mouse does.
import type { Canvas, FabricObject } from "fabric";

const ART_W = 384, ART_H = 400;

// ---- change log (canvas_since) ----
export type Change = { seq: number; at: string; by: string; what: string };   // by: "person" or the agent's name
const log: Change[] = [];
let seq = 0;
/** live.ts sets window.__agentCall while an agent's call runs, so its changes are marked "agent". */
export function note(what: string) {
  const c = { seq: ++seq, at: new Date().toISOString(), by: (window as any).__agentCall ? String((window as any).__agentName ?? "agent") : "person", what };
  log.push(c);
  if (log.length > 500) log.shift();
  // the server keeps each canvas's log (workspace/canvases/<id>.log.jsonl): it outlives a reload,
  // and canvas_since reads it even when no page is open
  const id = new URLSearchParams(location.search).get("canvas")?.toLowerCase() || "main";
  fetch(`/api/canvas/${id}/log`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ by: c.by, what: c.what, at: c.at }), keepalive: true }).catch(() => {});
}
export function since(cursor = 0, limit = 100) {
  const rows = log.filter((c) => c.seq > cursor).slice(-limit);
  return { cursor: seq, changes: rows, dropped: log.length && log[0].seq > cursor + 1 ? log[0].seq - cursor - 1 : 0 };
}

// ---- refs ----
let refs = new Map<string, Element | FabricObject>();
const visible = (el: Element) => {
  const r = el.getBoundingClientRect();
  const s = getComputedStyle(el);
  return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
};
const nameOf = (el: Element): string => {
  const h = el as HTMLElement;
  const text = (h.innerText || "").trim(), title = (h.getAttribute("title") || "").trim();
  // icon buttons (✎, ▭) are named by their title; the rest by what they say
  const t = (h.getAttribute("aria-label") || (text.length > 2 ? text : title || text) || (h as HTMLInputElement).placeholder || (h as HTMLInputElement).value || "").trim();
  return t.replace(/\s+/g, " ").slice(0, 60);
};
const roleOf = (el: Element) => {
  const t = el.tagName.toLowerCase();
  if (t === "input") return `input:${(el as HTMLInputElement).type}`;
  if (el.closest("[data-layer]") === el) return "layer-row";
  return t;
};
const layerName = (o: FabricObject) => (o as any).name ?? o.type;

/** Every control on the page and every object on the artboard, numbered for this snapshot. */
function collect(c: Canvas) {
  refs = new Map();
  const items: { ref: string; role: string; name: string; box: string; extra?: string }[] = [];
  let n = 0;
  const sel = "button, input, select, textarea, a[href], [data-layer], label:has(input[type=file])";
  for (const el of document.querySelectorAll(sel)) {
    if (!visible(el) || el.closest("label:has(input[type=file])") !== el && el.matches("input[type=file]")) continue;
    const ref = `e${++n}`;
    refs.set(ref, el);
    const r = el.getBoundingClientRect();
    const h = el as HTMLElement;
    const state = [h.classList.contains("sel") || h.classList.contains("ring-1") ? "selected" : "",
      (h as HTMLButtonElement).disabled ? "disabled" : "",
      (h as HTMLInputElement).type === "checkbox" ? ((h as HTMLInputElement).checked ? "checked" : "unchecked") : ""].filter(Boolean).join(" ");
    items.push({ ref, role: roleOf(el), name: nameOf(el), box: `${r.x | 0},${r.y | 0} ${r.width | 0}x${r.height | 0}`, extra: state || undefined });
  }
  const active = c.getActiveObjects();
  c.getObjects().slice().reverse().forEach((o, i) => {
    const ref = `l${i + 1}`;
    refs.set(ref, o);
    const b = o.getBoundingRect();
    const fill = typeof o.fill === "string" && o.fill ? o.fill : typeof o.stroke === "string" ? o.stroke : "";
    items.push({ ref, role: `art:${o.type}`, name: layerName(o), box: `${b.left | 0},${b.top | 0} ${b.width | 0}x${b.height | 0}`,
      extra: [active.includes(o) ? "selected" : "", o.visible ? "" : "hidden", (o as any).locked ? "locked" : "", fill, (o as any).text ? `"${(o as any).text}"` : ""].filter(Boolean).join(" ") || undefined });
  });
  return items;
}

export function snapshot(c: Canvas, grep?: string) {
  const items = collect(c);   // refs come from the full tree even when grep filters the lines
  const lines = items.map((i) => `${i.role} "${i.name}" [ref=${i.ref}] @${i.box}${i.extra ? ` (${i.extra})` : ""}`);
  const re = grep ? new RegExp(grep, "i") : null;
  return {
    note: "page boxes are CSS px; art:* boxes are artboard px (384 x 400). Tap a ref, or tap/drag artboard x,y.",
    tree: (re ? lines.filter((l) => re.test(l)) : lines).join("\n"),
    count: lines.length,
  };
}

export function query(c: Canvas, q: { text?: string; textContains?: string; role?: string }) {
  const items = collect(c);
  const keys = Object.entries(q).filter(([, v]) => v);
  if (keys.length !== 1) throw new Error("give exactly one of text, textContains, role");
  const [k, v] = keys[0];
  const hit = items.filter((i) => k === "text" ? i.name === v : k === "textContains" ? i.name.toLowerCase().includes(String(v).toLowerCase()) : i.role === v || i.role.startsWith(String(v)));
  return hit.map((i) => ({ ref: i.ref, role: i.role, name: i.name, box: i.box, state: i.extra }));
}

function resolve(c: Canvas, a: { ref?: string; text?: string; textContains?: string; role?: string }) {
  if (a.ref) {
    if (!refs.size) collect(c);
    const t = refs.get(a.ref);
    if (!t) throw new Error(`no ref ${a.ref}: take a snapshot first (refs change when the page does)`);
    return t;
  }
  const hits = query(c, a as any);
  if (hits.length !== 1) throw new Error(`${hits.length} matches: ${hits.slice(0, 6).map((h) => `${h.ref} ${h.name}`).join("; ")}. Use a ref.`);
  return refs.get(hits[0].ref)!;
}

// ---- pointer on the artboard ----
function toClient(c: Canvas, x: number, y: number) {
  const r = c.upperCanvasEl.getBoundingClientRect();
  return { clientX: r.left + (x / ART_W) * r.width, clientY: r.top + (y / ART_H) * r.height };
}
function fire(target: EventTarget, type: string, p: { clientX: number; clientY: number }, down: boolean) {
  const init = { ...p, bubbles: true, cancelable: true, composed: true, pointerId: 1, pointerType: "mouse", isPrimary: true, button: 0, buttons: down ? 1 : 0, view: window };
  target.dispatchEvent(new PointerEvent(type, init));
  const mouse = { pointerdown: "mousedown", pointermove: "mousemove", pointerup: "mouseup" }[type];
  if (mouse) target.dispatchEvent(new MouseEvent(mouse, init));
}
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** A real pointer path on the artboard: down at the first point, through the rest, up at the last. */
export async function drag(c: Canvas, points: number[][], durationMs = 300) {
  if (points.length < 1) throw new Error("points: [[x, y], ...]");
  const up = c.upperCanvasEl;
  const first = toClient(c, points[0][0], points[0][1]);
  fire(up, "pointerdown", first, true);
  const step = Math.max(0, durationMs / Math.max(1, points.length - 1));
  for (const [x, y] of points.slice(1)) {
    await sleep(step);
    const p = toClient(c, x, y);
    fire(up, "pointermove", p, true);
    fire(document, "pointermove", p, true);
  }
  const last = toClient(c, points.at(-1)![0], points.at(-1)![1]);
  fire(up, "pointerup", last, false);
  fire(document, "pointerup", last, false);
  await sleep(50);
  c.requestRenderAll();
}

export async function tap(c: Canvas, a: { ref?: string; text?: string; textContains?: string; role?: string; x?: number; y?: number }) {
  if (a.x !== undefined && a.y !== undefined && !a.ref) { await drag(c, [[a.x, a.y]], 0); return { tapped: `artboard ${a.x},${a.y}` }; }
  const t = resolve(c, a);
  if (t instanceof Element) {
    const h = t as HTMLElement;
    if (h.matches("input[type=checkbox]")) h.click();
    else if (h.matches("input, textarea, select")) h.focus();
    else if (h.matches("label")) (h.querySelector("input") as HTMLInputElement)?.click();
    else h.click();
    return { tapped: `${roleOf(t)} "${nameOf(t)}"` };
  }
  c.setActiveObject(t); c.requestRenderAll();
  return { tapped: `layer "${layerName(t)}" (selected)` };
}

/** Text into an input / textarea (React sees it), or the text of a text layer. */
export function type(c: Canvas, a: { text: string; ref?: string }) {
  const t = a.ref ? resolve(c, { ref: a.ref }) : (document.activeElement && document.activeElement !== document.body ? document.activeElement : c.getActiveObject());
  if (!t) throw new Error("nothing focused: give a ref (an input, or a text layer)");
  if (t instanceof Element) {
    const el = t as HTMLInputElement;
    if (!el.matches("input, textarea")) throw new Error(`${roleOf(t)} takes no text`);
    const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(el, a.text);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    return { typed: a.text, into: nameOf(t) };
  }
  if (!("text" in (t as any))) throw new Error(`layer "${layerName(t)}" is not text`);
  (t as any).set({ text: a.text });
  c.requestRenderAll();
  c.fire("object:modified", { target: t } as any);
  return { typed: a.text, into: `layer "${layerName(t)}"` };
}

/** A key as a person presses it: shortcuts (v b e r o t, Delete, Escape) or Cmd/Ctrl combos. */
export function key(a: { key: string; meta?: boolean; shift?: boolean }) {
  const init = { key: a.key, metaKey: !!a.meta, ctrlKey: !!a.meta, shiftKey: !!a.shift, bubbles: true, cancelable: true };
  (document.activeElement ?? document.body).dispatchEvent(new KeyboardEvent("keydown", init));   // bubbles to window
  return { pressed: `${a.meta ? "Cmd-" : ""}${a.shift ? "Shift-" : ""}${a.key}` };
}
