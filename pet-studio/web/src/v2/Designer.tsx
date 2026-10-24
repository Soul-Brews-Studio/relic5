// Pet Studio v2: a designer's canvas for the pet's sprite. Draw, paste or generate pictures into a
// frame, stack them as layers, give a state its own frames, then Create sprite makes the pack
// (96 x 100 GIFs, the seven states the pet plays) and sends it to the pet.
//
// The artboard is 384 x 400 (4x the pet's 96 x 100 frame) so drawing stays smooth; the server
// scales every frame down. fabric.js holds the objects (layers); each frame is a fabric JSON.
import { useEffect, useRef, useState } from "react";
import { Canvas, Ellipse, FabricImage, FabricObject, IText, loadSVGFromString, Path, PencilBrush, Rect, util, type TPointerEventInfo } from "fabric";
import { Brush, ChevronDown, ChevronUp, Circle, Copy, Eraser, Eye, EyeOff, ImagePlus, Lock, LockOpen, MousePointer2,
  Pause, Play, Plus, Redo2, Scissors, Send, Sparkles, Square, Trash2, Type as TypeIcon, Undo2, X, type LucideIcon } from "lucide-react";
import { api, type Job, type State } from "../api";
import { helloDesigner, setActions, startLive } from "../live";
import * as ui from "./ui";

// fabric 7 anchors objects at their centre by default; every position here is a top-left corner
FabricObject.ownDefaults.originX = "left";
FabricObject.ownDefaults.originY = "top";
// selection is the printer's cut line: CutContour magenta, dashed, round handles
Object.assign(FabricObject.ownDefaults, {
  borderColor: "#d6006f", borderDashArray: [6, 4], borderScaleFactor: 1.5, cornerColor: "#ffffff",
  cornerStrokeColor: "#d6006f", cornerStyle: "circle", cornerSize: 11, transparentCorners: false, padding: 4,
});
/** The process-colour bar printed along a sticker sheet's edge: the palette, one click each. */
const SWATCHES = ["#16181d", "#ffffff", "#d6006f", "#0087c9", "#ffdd00", "#f2994a", "#ff3b5c", "#2e7d32", "#7c4dff", "#8d6e63", "#9aa3b2", "#ffd6e7"];

const W = 384, H = 400;
const STATES = ["idle", "busy", "attention", "celebrate", "dizzy", "sleep", "heart"] as const;
type StateName = (typeof STATES)[number];
const HINT: Record<StateName, string> = {
  idle: "frame 1 here is the base: every state you leave empty is made from it",
  busy: "working: an agent is running", attention: "an agent is waiting for you", celebrate: "a job finished",
  dizzy: "too much at once", sleep: "nobody is working", heart: "someone tapped the pet",
};
type Tool = "select" | "brush" | "eraser" | "rect" | "ellipse" | "text";
const TOOLS: { id: Tool; icon: LucideIcon; label: string; key: string }[] = [
  { id: "select", icon: MousePointer2, label: "Select / move", key: "v" },
  { id: "brush", icon: Brush, label: "Brush", key: "b" },
  { id: "eraser", icon: Eraser, label: "Eraser", key: "e" },
  { id: "rect", icon: Square, label: "Rectangle", key: "r" },
  { id: "ellipse", icon: Circle, label: "Ellipse", key: "o" },
  { id: "text", icon: TypeIcon, label: "Text", key: "t" },
];
type Frame = { json: any | null; png: string | null };
type Frames = Record<StateName, Frame[]>;
const emptyFrames = (): Frames => Object.fromEntries(STATES.map((s) => [s, [{ json: null, png: null }]])) as Frames;
const PROPS = ["name", "erase"];
let nameSeq = 0;
const label = (o: FabricObject) => (o as any).name ?? o.type;

async function poll(id: string, onJob: (j: Job) => void): Promise<Job> {
  for (;;) {
    const j = await api.job(id);
    onJob(j);
    if (j.status === "ok" || j.status === "failed") return j;
    await new Promise((r) => setTimeout(r, 700));
  }
}

/** Which canvas this page shows: /v2?canvas=<id> (default "main"). Agents address it by that id. */
export const CANVAS_ID = (() => {
  const v = new URLSearchParams(location.search).get("canvas")?.toLowerCase() ?? "main";
  return /^[a-z0-9_-]{1,32}$/.test(v) ? v : "main";
})();

export function Designer() {
  const el = useRef<HTMLCanvasElement>(null);
  const cv = useRef<Canvas | null>(null);
  // start at a zoom that fits the screen (1.5x on a desktop, smaller on a phone)
  const [zoom, setZoom] = useState(() => Math.max(0.5, Math.min(1.5, Math.floor(((window.innerWidth - 90) / W) * 4) / 4)));
  const [tool, setToolState] = useState<Tool>("brush");
  const toolRef = useRef<Tool>("brush");
  const [color, setColor] = useState("#f2994a");
  const [size, setSize] = useState(14);
  const [rev, setRev] = useState(0);                  // re-render the layers panel
  const [frames, setFrames] = useState<Frames>(emptyFrames);
  const framesRef = useRef(frames);
  framesRef.current = frames;
  const [state, setState] = useState<StateName>("idle");
  const [fi, setFi] = useState(0);
  const cur = useRef({ state: "idle" as StateName, fi: 0 });
  const [onion, setOnion] = useState(true);
  const [fps, setFps] = useState(8);
  const [playing, setPlaying] = useState(false);
  // Play the sprite: the made pack's seven states in turn on the black pet screen, ~2 s each
  const [showIdx, setShowIdx] = useState<number | null>(null);
  const [playIdx, setPlayIdx] = useState(0);
  const history = useRef<{ stack: string[]; at: number; quiet: boolean }>({ stack: [], at: -1, quiet: false });
  const [name, setName] = useState("my-pet");
  const [prompt, setPrompt] = useState("");
  const [job, setJob] = useState<Job | null>(null);
  const [pack, setPack] = useState<any>(null);
  const [st, setSt] = useState<State | null>(null);
  const [err, setErr] = useState("");
  const guard = async (f: () => Promise<void>) => { setErr(""); try { await f(); } catch (e: any) { setErr(e.message ?? String(e)); } };

  // ---- canvas setup ----
  useEffect(() => {
    const c = new Canvas(el.current!, { width: W * zoom, height: H * zoom, preserveObjectStacking: true, selectionColor: "rgba(242,181,68,.15)", selectionBorderColor: "#f2b544" });
    c.setZoom(zoom);
    cv.current = c;
    (window as any).__designer = c;
    const bump = () => setRev((r) => r + 1);
    const record = () => {
      const h = history.current;
      if (h.quiet) return;
      h.stack = h.stack.slice(0, h.at + 1);
      h.stack.push(JSON.stringify(c.toObject(PROPS)));
      if (h.stack.length > 60) h.stack.shift();
      h.at = h.stack.length - 1;
      bump();
    };
    c.on("object:added", (e: any) => { if (!history.current.quiet && e.target?.type !== "path") ui.note(`added ${label(e.target)}`); record(); });
    c.on("object:removed", (e: any) => { if (!history.current.quiet) ui.note(`removed ${label(e.target)}`); record(); });
    c.on("object:modified", (e: any) => { ui.note(`changed ${e.target ? label(e.target) : "layer"}`); record(); });
    c.on("selection:created", bump);
    c.on("selection:updated", bump);
    c.on("selection:cleared", bump);
    c.on("path:created", (e: any) => {
      const p = e.path as FabricObject;
      (p as any).name = toolRef.current === "eraser" ? `eraser ${++nameSeq}` : `stroke ${++nameSeq}`;
      if (toolRef.current === "eraser") { p.globalCompositeOperation = "destination-out"; (p as any).erase = true; }
      ui.note(`added ${(p as any).name}`);
      c.requestRenderAll();
      record();
    });

    // shapes and text: press, drag to size, release
    let drawing: FabricObject | null = null, ox = 0, oy = 0;
    c.on("mouse:down", (o: TPointerEventInfo) => {
      const t = toolRef.current;
      if (t !== "rect" && t !== "ellipse" && t !== "text") return;
      const p = c.getScenePoint(o.e);
      ox = p.x; oy = p.y;
      const fill = colorRef.current;
      if (t === "text") {
        const tx = new IText("text", { left: p.x, top: p.y, fill, fontSize: 48, fontFamily: "Arial Black, Arial, sans-serif", fontWeight: "bold" });
        (tx as any).name = `text ${++nameSeq}`;
        c.add(tx); c.setActiveObject(tx); tx.enterEditing(); tx.selectAll();
        setTool("select");
        return;
      }
      drawing = t === "rect"
        ? new Rect({ left: p.x, top: p.y, width: 1, height: 1, fill, rx: 6, ry: 6 })
        : new Ellipse({ left: p.x, top: p.y, rx: 1, ry: 1, fill });
      (drawing as any).name = `${t} ${++nameSeq}`;
      history.current.quiet = true;
      c.add(drawing);
    });
    c.on("mouse:move", (o: TPointerEventInfo) => {
      if (!drawing) return;
      const p = c.getScenePoint(o.e);
      const l = Math.min(ox, p.x), t = Math.min(oy, p.y), w = Math.abs(p.x - ox), h = Math.abs(p.y - oy);
      if (drawing instanceof Ellipse) drawing.set({ left: l, top: t, rx: w / 2, ry: h / 2 });
      else drawing.set({ left: l, top: t, width: w, height: h });
      c.requestRenderAll();
    });
    c.on("mouse:up", () => {
      if (!drawing) return;
      const d = drawing; drawing = null;
      history.current.quiet = false;
      if ((d.width ?? 0) < 3 && (d.height ?? 0) < 3) d.set(d instanceof Ellipse ? { rx: 30, ry: 30 } : { width: 60, height: 60 });
      d.setCoords();
      c.setActiveObject(d);
      ui.note(`added ${label(d)}`);
      record();
    });
    record();
    return () => { c.dispose(); cv.current = null; };
  }, []);

  useEffect(() => { const c = cv.current; if (!c) return; c.setDimensions({ width: W * zoom, height: H * zoom }); c.setZoom(zoom); c.requestRenderAll(); }, [zoom]);

  const colorRef = useRef(color);
  colorRef.current = color;
  const setTool = (t: Tool) => {
    if (t !== toolRef.current) ui.note(`tool ${t}`);
    toolRef.current = t; setToolState(t);
    const c = cv.current!;
    c.isDrawingMode = t === "brush" || t === "eraser";
    if (c.isDrawingMode) {
      const b = new PencilBrush(c);
      b.width = size; b.color = t === "eraser" ? "#000000" : color;
      c.freeDrawingBrush = b;
    }
    c.selection = t === "select";
    c.getObjects().forEach((o) => { if (!(o as any).locked) o.selectable = t === "select"; });
    if (t !== "select") c.discardActiveObject();
    c.requestRenderAll();
  };
  useEffect(() => { const b = cv.current?.freeDrawingBrush; if (b) { b.width = size; if (toolRef.current === "brush") b.color = color; } }, [size, color]);
  useEffect(() => { setTool("brush"); }, []);

  // the selected object follows the colour picker
  const active = cv.current?.getActiveObject();
  const recolor = (c: string) => {
    setColor(c);
    const o = cv.current?.getActiveObject();
    if (!o) return;
    if (o.type === "path") o.set({ stroke: c }); else o.set({ fill: c });
    cv.current!.requestRenderAll();
    cv.current!.fire("object:modified", { target: o } as any);
  };

  // ---- images: upload, paste, drop, generate ----
  const addImage = async (url: string, nm = "image") => {
    const img = await FabricImage.fromURL(url, { crossOrigin: "anonymous" });
    const s = Math.min((W * 0.8) / img.width, (H * 0.8) / img.height, 1);
    img.set({ scaleX: s, scaleY: s, left: (W - img.width * s) / 2, top: (H - img.height * s) / 2 });
    (img as any).name = `${nm} ${++nameSeq}`;
    cv.current!.add(img);
    setTool("select");
    cv.current!.setActiveObject(img);
    return img;
  };
  /** Cut a plain background out of the selected picture: flood-fill from the four corners,
   * colours within a small tolerance of each corner become transparent (as make-pack.sh does). */
  const removeBackground = async () => {
    const c = cv.current!, o = c.getActiveObject();
    if (!(o instanceof FabricImage)) return;
    const src = o.getElement() as HTMLImageElement;
    const k = document.createElement("canvas");
    k.width = src.naturalWidth || src.width; k.height = src.naturalHeight || src.height;
    const g = k.getContext("2d")!;
    g.drawImage(src, 0, 0);
    const d = g.getImageData(0, 0, k.width, k.height), px = d.data, w = k.width, h = k.height;
    const seen = new Uint8Array(w * h), tol = 26;
    for (const [sx, sy] of [[0, 0], [w - 1, 0], [0, h - 1], [w - 1, h - 1]]) {
      const i0 = (sy * w + sx) * 4, r0 = px[i0], g0 = px[i0 + 1], b0 = px[i0 + 2];
      if (px[i0 + 3] === 0) continue;
      const stack = [sy * w + sx];
      while (stack.length) {
        const p = stack.pop()!;
        if (seen[p]) continue;
        const i = p * 4;
        if (Math.abs(px[i] - r0) > tol || Math.abs(px[i + 1] - g0) > tol || Math.abs(px[i + 2] - b0) > tol) continue;
        seen[p] = 1; px[i + 3] = 0;
        const x = p % w, y = (p / w) | 0;
        if (x > 0) stack.push(p - 1); if (x < w - 1) stack.push(p + 1);
        if (y > 0) stack.push(p - w); if (y < h - 1) stack.push(p + w);
      }
    }
    g.putImageData(d, 0, 0);
    const img = await FabricImage.fromURL(k.toDataURL("image/png"));
    img.set({ left: o.left, top: o.top, scaleX: o.scaleX, scaleY: o.scaleY, angle: o.angle, opacity: o.opacity });
    (img as any).name = `${label(o)} (cut out)`;
    const at = c.getObjects().indexOf(o);
    c.remove(o);
    c.insertAt(at, img);
    c.setActiveObject(img);
    c.requestRenderAll();
  };
  /** SVG stays vector: its paths, shapes and text become fabric objects, one group (default) or,
   * with split, one layer each. Fitted to 80 % of the artboard unless a width is given. */
  const addSvg = async (svg: string, o: { x?: number; y?: number; width?: number; split?: boolean; name?: string } = {}) => {
    const { objects, options } = await loadSVGFromString(svg);
    const parts = objects.filter(Boolean) as FabricObject[];
    if (!parts.length) throw new Error("the SVG has no drawable elements");
    const c = cv.current!;
    const g = util.groupSVGElements(parts, options);
    const target = o.width ?? Math.min(W * 0.8, (H * 0.8) * g.width / Math.max(1, g.height));
    const sc = target / Math.max(1, g.width);
    const left = o.x ?? (W - g.width * sc) / 2, top = o.y ?? (H - g.height * sc) / 2;
    g.set({ scaleX: sc, scaleY: sc, left, top });
    g.setCoords();
    const nm = o.name ?? "svg";
    if (!o.split || !(g as any).getObjects) {
      (g as any).name = `${nm} ${++nameSeq}`;
      c.add(g);
      setTool("select"); c.setActiveObject(g);
      return [g];
    }
    // split: fabric puts each part back in canvas coordinates as it leaves the group
    history.current.quiet = true;
    c.add(g);
    const out = (g as any).removeAll() as FabricObject[];
    c.remove(g);
    history.current.quiet = false;
    for (const k of out) {
      (k as any).name = `${nm} ${k.type} ${++nameSeq}`;
      k.setCoords();
      c.add(k);
    }
    setTool("select");
    return out;
  };
  const readText = (f: File) => new Promise<string>((ok) => { const r = new FileReader(); r.onload = () => ok(String(r.result)); r.readAsText(f); });
  const place = async (f: File) => {
    const nm = f.name.replace(/\.[^.]+$/, "");
    if (f.type === "image/svg+xml" || f.name.toLowerCase().endsWith(".svg")) await addSvg(await readText(f), { name: nm });
    else await addImage(await readFile(f), nm);
  };
  const readFile = (f: File) => new Promise<string>((ok) => { const r = new FileReader(); r.onload = () => ok(String(r.result)); r.readAsDataURL(f); });
  useEffect(() => {
    const paste = async (e: ClipboardEvent) => {
      const f = [...(e.clipboardData?.files ?? [])].find((x) => x.type.startsWith("image/"));
      if (f) { e.preventDefault(); addImage(await readFile(f), "pasted"); }
    };
    window.addEventListener("paste", paste);
    return () => window.removeEventListener("paste", paste);
  }, []);
  const generate = () => guard(async () => {
    const nm = (name || "img").replace(/[^a-z0-9_-]/g, "").slice(0, 16) + "-" + (Date.now() % 10000);
    const r = await fetch("/api/images/generate", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: nm, prompt }) }).then((x) => x.json());
    if (r.error) throw new Error(r.error);
    const j = await poll(r.job, setJob);
    if (j.status !== "ok") throw new Error(j.error ?? "image generation failed");
    await addImage(`${j.result.url}?t=${Date.now()}`, "generated");
  });

  // ---- keyboard ----
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const c = cv.current!;
      const editing = (c.getActiveObject() as any)?.isEditing || (e.target as HTMLElement)?.closest("input, textarea");
      if (editing) return;
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") { e.preventDefault(); e.shiftKey ? redo() : undo(); return; }
      if (e.key === "Delete" || e.key === "Backspace") { removeSelected(); e.preventDefault(); return; }
      const t = TOOLS.find((x) => x.key === e.key.toLowerCase());
      if (t && !e.metaKey && !e.ctrlKey) setTool(t.id);
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [size, color]);

  const restore = async (json: string) => {
    const c = cv.current!, h = history.current;
    h.quiet = true;
    await c.loadFromJSON(JSON.parse(json));
    c.getObjects().forEach((o) => { if ((o as any).erase) o.globalCompositeOperation = "destination-out"; });
    h.quiet = false;
    c.requestRenderAll();
    setRev((r) => r + 1);
  };
  const undo = () => { const h = history.current; if (h.at > 0) { h.at--; restore(h.stack[h.at]); } };
  const redo = () => { const h = history.current; if (h.at < h.stack.length - 1) { h.at++; restore(h.stack[h.at]); } };
  const removeSelected = () => {
    const c = cv.current!;
    c.getActiveObjects().forEach((o) => c.remove(o));
    c.discardActiveObject(); c.requestRenderAll();
  };

  // ---- frames ----
  const exportPng = () => cv.current!.toDataURL({ format: "png", multiplier: 1 / zoom });
  const isEmpty = () => cv.current!.getObjects().length === 0;
  const saveCurrent = (): Frames => {
    const { state: s, fi: i } = cur.current;
    const next = { ...framesRef.current, [s]: framesRef.current[s].map((f, k) => k === i ? { json: cv.current!.toObject(PROPS), png: isEmpty() ? null : exportPng() } : f) };
    framesRef.current = next;
    setFrames(next);
    return next;
  };
  const openFrame = async (s: StateName, i: number, fr: Frames = framesRef.current) => {
    const f = fr[s][i];
    const c = cv.current!, h = history.current;
    h.quiet = true;
    c.clear();
    if (f?.json) await c.loadFromJSON(f.json);
    c.getObjects().forEach((o) => { if ((o as any).erase) o.globalCompositeOperation = "destination-out"; });
    h.quiet = false;
    h.stack = [JSON.stringify(c.toObject(PROPS))]; h.at = 0;
    cur.current = { state: s, fi: i };
    ui.note(`opened ${s} frame ${i + 1}`);
    setState(s); setFi(i);
    setTool(toolRef.current);
    c.requestRenderAll();
    setRev((r) => r + 1);
  };
  const goto = (s: StateName, i: number) => { const fr = saveCurrent(); openFrame(s, i, fr); };
  const addFrame = (dup: boolean) => {
    const fr = saveCurrent();
    const { state: s, fi: i } = cur.current;
    const copy = dup ? { ...fr[s][i] } : { json: null, png: null };
    const list = [...fr[s].slice(0, i + 1), copy, ...fr[s].slice(i + 1)];
    const next = { ...fr, [s]: list };
    framesRef.current = next; setFrames(next);
    openFrame(s, i + 1, next);
  };
  const deleteFrame = () => {
    const fr = saveCurrent();
    const { state: s, fi: i } = cur.current;
    if (fr[s].length === 1) { cv.current!.clear(); saveCurrent(); return; }
    const next = { ...fr, [s]: fr[s].filter((_, k) => k !== i) };
    framesRef.current = next; setFrames(next);
    openFrame(s, Math.max(0, i - 1), next);
  };

  // playback of the current state's frames
  useEffect(() => {
    if (!playing) return;
    saveCurrent();
    const t = setInterval(() => setPlayIdx((p) => p + 1), 1000 / fps);
    return () => clearInterval(t);
  }, [playing, fps, state]);
  const playFrames = frames[state].map((f) => f.png).filter(Boolean) as string[];

  // ---- create sprite ----
  const doCreate = async (nm: string, f: number): Promise<any> => {
    const fr = saveCurrent();
    const base = fr.idle[0]?.png;
    if (!base) throw new Error("draw or place something in idle, frame 1: it is the base of the sprite");
    const states: Record<string, string[]> = {};
    for (const s of STATES) {
      const pngs = fr[s].map((f) => f.png).filter(Boolean) as string[];
      if (s === "idle" ? pngs.length > 1 : pngs.length > 0) states[s] = pngs;
    }
    const design = Object.fromEntries(STATES.map((s) => [s, fr[s].map((f) => f.json)]));
    const r = await fetch("/api/sprite/create", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: nm, base, states, fps: f, design }) }).then((x) => x.json());
    if (r.error) throw new Error(r.error);
    setPack(null);
    const j = await poll(r.job, setJob);
    if (j.status !== "ok") throw new Error(j.error ?? "create sprite failed");
    setPack(j.result);
    ui.note(`created sprite ${nm} (${(j.result.drawn ?? []).join(", ") || "all states from the base"})`);
    return j.result;
  };
  const create = () => guard(async () => { await doCreate(name, fps); });
  const doSend = async (nm: string, pet?: string) => {
    const r = await api.flashBle({ kind: "pack", name: nm, pet });
    const j = await poll(r.job, setJob);
    if (j.status !== "ok") throw new Error(j.error ?? "send failed");
    return j.result;
  };
  const send = () => guard(async () => { await doSend(pack.name); });

  // ---- auto sprite: idle frame 1 is the one picture; the AI redraws every pose, checks its own
  // frames, redraws the bad ones, places them in this canvas's frames and makes the pack ----
  const [auto, setAuto] = useState<any>(null);
  const doAuto = async (nm: string, opts: { send?: boolean; moves?: Record<string, string[]> } = {}) => {
    const fr = saveCurrent();
    const ref = fr.idle[0]?.png;
    if (!ref) throw new Error("put the character in idle, frame 1: that one picture is all the AI needs");
    const r = await fetch("/api/sprite/auto", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: nm, imageBase64: ref, canvas: CANVAS_ID, by: "auto sprite", send: !!opts.send, moves: opts.moves }) }).then((x) => x.json());
    if (r.error) throw new Error(r.error);
    setPack(null); setAuto(null);
    const j = await poll(r.job, setJob);
    if (j.status !== "ok") throw new Error(j.error ?? "auto sprite failed");
    setPack(j.result); setAuto(j.result);
    ui.note(`auto sprite ${nm}: ${j.result.reviews?.map((v: any) => v.ok ? "passed" : `redrew ${v.bad.join(", ")}`).join(" → ")}`);
    return j.result;
  };

  // ---- every action, for the agent (MCP petstudio design_* tools via /api/live/call) ----
  // Coordinates are artboard pixels: 384 x 400 (the pet's 96 x 100 frame at 4x).
  const find = (n: string | number | undefined): FabricObject => {
    const all = cv.current!.getObjects();
    const o = typeof n === "number" ? all[all.length - 1 - n] : all.find((x) => label(x) === n) ?? all.find((x) => label(x).startsWith(String(n)));
    if (!o) throw new Error(`no layer ${n}; layers: ${all.map(label).reverse().join(", ") || "none"}`);
    return o;
  };
  const layerInfo = (o: FabricObject) => ({
    name: label(o), type: o.type, left: Math.round(o.left), top: Math.round(o.top),
    width: Math.round(o.getScaledWidth()), height: Math.round(o.getScaledHeight()), angle: Math.round(o.angle ?? 0),
    opacity: o.opacity, visible: o.visible, locked: !!(o as any).locked, fill: typeof o.fill === "string" ? o.fill : null,
    stroke: typeof o.stroke === "string" ? o.stroke : null,
  });
  const select = (o: FabricObject) => { setTool("select"); cv.current!.setActiveObject(o); cv.current!.requestRenderAll(); setRev((r) => r + 1); };
  setActions({
    view: () => (saveCurrent(), {
      state: cur.current.state, frame: cur.current.fi + 1,
      frames: Object.fromEntries(STATES.map((s) => [s, `${framesRef.current[s].filter((f) => f.png).length}/${framesRef.current[s].length} drawn`])),
      layers: cv.current!.getObjects().slice().reverse().map(layerInfo),
      tool: toolRef.current, color: colorRef.current, size, zoom, artboard: { width: W, height: H, petFrame: "96 x 100" },
      png: isEmpty() ? null : exportPng(), pack: pack?.name ?? null,
    }),
    goto: async ({ state: s, frame }: any) => {
      if (!STATES.includes(s)) throw new Error(`state: ${STATES.join(", ")}`);
      const n = Math.max(1, Number(frame ?? 1));
      const fr = saveCurrent();
      const list = [...fr[s as StateName]];
      while (list.length < n) list.push({ json: null, png: null });
      const next = { ...fr, [s]: list };
      framesRef.current = next; setFrames(next);
      await openFrame(s, n - 1, next);
      return { state: s, frame: n, of: framesRef.current[s as StateName].length };
    },
    frame: ({ op }: any) => {
      if (op === "add") addFrame(false); else if (op === "duplicate") addFrame(true); else if (op === "delete") deleteFrame();
      else throw new Error("op: add, duplicate or delete");
      return { op };
    },
    stroke: ({ points, color: c = colorRef.current, size: w = size, erase = false }: any) => {
      if (!Array.isArray(points) || points.length < 2) throw new Error("points: [[x, y], ...] at least two");
      const d = points.map(([x, y]: number[], i: number) => `${i ? "L" : "M"} ${x} ${y}`).join(" ");
      const p = new Path(d, { stroke: erase ? "#000" : c, strokeWidth: w, fill: "", strokeLineCap: "round", strokeLineJoin: "round" });
      (p as any).name = erase ? `eraser ${++nameSeq}` : `stroke ${++nameSeq}`;
      if (erase) { p.globalCompositeOperation = "destination-out"; (p as any).erase = true; }
      cv.current!.add(p);
      return layerInfo(p);
    },
    shape: ({ kind = "rect", x = 100, y = 100, w = 120, h = 80, color: c = colorRef.current, opacity = 1, radius = 6 }: any) => {
      const o = kind === "ellipse"
        ? new Ellipse({ left: x, top: y, rx: w / 2, ry: h / 2, fill: c, opacity })
        : new Rect({ left: x, top: y, width: w, height: h, fill: c, opacity, rx: radius, ry: radius });
      (o as any).name = `${kind === "ellipse" ? "ellipse" : "rect"} ${++nameSeq}`;
      cv.current!.add(o);
      return layerInfo(o);
    },
    text: ({ text = "text", x = 40, y = 40, size: fs = 48, color: c = colorRef.current }: any) => {
      const t = new IText(String(text), { left: x, top: y, fill: c, fontSize: fs, fontFamily: "Arial Black, Arial, sans-serif", fontWeight: "bold" });
      (t as any).name = `text ${++nameSeq}`;
      cv.current!.add(t);
      return layerInfo(t);
    },
    image: async ({ url, prompt: pr, x, y, width, remove_background }: any) => {
      let u = url;
      if (!u && pr) {
        const nm = "gen-" + (Date.now() % 100000);
        const r = await fetch("/api/images/generate", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: nm, prompt: pr }) }).then((q) => q.json());
        if (r.error) throw new Error(r.error);
        const j = await poll(r.job, setJob);
        if (j.status !== "ok") throw new Error(j.error ?? "image generation failed");
        u = `${j.result.url}?t=${Date.now()}`;
      }
      if (!u) throw new Error("give url, path or prompt");
      const img = await addImage(u, pr ? "generated" : "image");
      if (width) { const sc = Number(width) / img.width; img.set({ scaleX: sc, scaleY: sc }); }
      if (x !== undefined) img.set({ left: Number(x) });
      if (y !== undefined) img.set({ top: Number(y) });
      img.setCoords();
      if (remove_background) await removeBackground();
      cv.current!.requestRenderAll();
      return layerInfo(cv.current!.getActiveObject() ?? img);
    },
    svg: async ({ svg, url, x, y, width, split = false, name: nm }: any) => {
      let text = svg;
      if (!text && url) text = String(url).startsWith("data:") ? (String(url).includes(";base64,") ? atob(String(url).split(",")[1]) : decodeURIComponent(String(url).split(",")[1])) : await (await fetch(url)).text();
      if (!text) throw new Error("give svg (the markup), path or url");
      const objs = await addSvg(String(text), { x, y, width, split, name: nm });
      cv.current!.requestRenderAll();
      return objs.map(layerInfo);
    },
    layer: async ({ name: n, op = "update", props = {} }: any) => {
      const c = cv.current!, o = find(n);
      switch (op) {
        case "select": select(o); break;
        case "update": {
          const { x, y, width, height, ...rest } = props;
          if (x !== undefined) o.set({ left: x });
          if (y !== undefined) o.set({ top: y });
          if (width) o.set({ scaleX: Number(width) / (o.width || 1) });
          if (height) o.set({ scaleY: Number(height) / (o.height || 1) });
          if (rest.color) { if (o.type === "path") o.set({ stroke: rest.color }); else o.set({ fill: rest.color }); delete rest.color; }
          o.set(rest); o.setCoords(); c.fire("object:modified", { target: o } as any); break;
        }
        case "up": c.bringObjectForward(o); break;
        case "down": c.sendObjectBackwards(o); break;
        case "top": c.bringObjectToFront(o); break;
        case "bottom": c.sendObjectToBack(o); break;
        case "delete": c.remove(o); break;
        case "show": case "hide": o.set({ visible: op === "show" }); break;
        case "lock": case "unlock": (o as any).locked = op === "lock"; o.set({ selectable: op === "unlock", evented: op === "unlock" }); break;
        case "remove_background": select(o); await removeBackground(); break;
        default: throw new Error("op: select, update, up, down, top, bottom, delete, show, hide, lock, unlock, remove_background");
      }
      c.requestRenderAll(); setRev((r) => r + 1);
      return op === "delete" ? { deleted: n } : layerInfo(c.getActiveObject() && op === "remove_background" ? c.getActiveObject()! : o);
    },
    clear: () => { cv.current!.clear(); saveCurrent(); setRev((r) => r + 1); return { cleared: true }; },
    undo: () => { undo(); return { ok: true }; },
    redo: () => { redo(); return { ok: true }; },
    tool: ({ tool: t, color: c, size: sz, zoom: z, onion: on }: any) => {
      if (t) { if (!TOOLS.some((x) => x.id === t)) throw new Error(`tool: ${TOOLS.map((x) => x.id).join(", ")}`); setTool(t); }
      if (c) setColor(c);
      if (sz) setSize(Number(sz));
      if (z) setZoom(Number(z));
      if (on !== undefined) setOnion(!!on);
      return { tool: t ?? toolRef.current, color: c ?? colorRef.current };
    },
    // droidread-style: see and drive the page the way a person does
    focus: () => ({
      state: cur.current.state, frame: cur.current.fi + 1, of: framesRef.current[cur.current.state].length, tool: toolRef.current,
      color: colorRef.current, size, zoom, selected: cv.current!.getActiveObjects().map(label), layers: cv.current!.getObjects().length,
      pack: pack?.name ?? null, job: job ? `${job.title}: ${job.status}` : null, changeCursor: ui.since(1e9).cursor,
    }),
    snapshot: ({ grep }: any) => ui.snapshot(cv.current!, grep),
    query: (q: any) => ui.query(cv.current!, q),
    screenshot: ({ width = 384 }: any) => ({ png: cv.current!.toDataURL({ format: "png", multiplier: (Number(width) || 384) / W / zoom }) }),
    tap: (a: any) => ui.tap(cv.current!, a),
    drag: async ({ points, durationMs }: any) => { await ui.drag(cv.current!, points, durationMs); return { dragged: points.length, tool: toolRef.current, layers: cv.current!.getObjects().length }; },
    type: (a: any) => ui.type(cv.current!, a),
    key: (a: any) => ui.key(a),
    since: ({ cursor = 0, limit = 100 }: any) => ui.since(Number(cursor), Number(limit)),
    create_sprite: async ({ name: nm = name, fps: f = fps }: any) => { setName(nm); return doCreate(nm, Number(f)); },
    send_to_pet: async ({ name: nm, pet }: any) => doSend(nm ?? pack?.name ?? name, pet),
  });
  // the canvas lives on the server (workspace/canvases/<id>.json): open it, and save as it changes
  const loaded = useRef(false);
  useEffect(() => {
    fetch(`/api/canvas/${CANVAS_ID}`).then((r) => (r.ok ? r.json() : null)).then(async (d) => {
      if (d?.frames) {
        const fr = { ...emptyFrames(), ...d.frames } as Frames;
        framesRef.current = fr; setFrames(fr);
        if (d.name) setName(d.name);
        if (d.fps) setFps(d.fps);
        await openFrame("idle", 0, fr);
      }
      loaded.current = true;
    }).catch(() => { loaded.current = true; });
  }, []);
  useEffect(() => {
    if (!loaded.current) return;
    const t = setTimeout(() => {
      const fr = saveCurrent();
      fetch(`/api/canvas/${CANVAS_ID}`, { method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ frames: fr, name, fps, savedAt: new Date().toISOString() }) }).catch(() => {});
    }, 1200);
    return () => clearTimeout(t);
  }, [rev, name, fps]);

  useEffect(() => {
    startLive();
    helloDesigner(CANVAS_ID);
    const hi = () => helloDesigner(CANVAS_ID);
    window.addEventListener("focus", hi);
    return () => window.removeEventListener("focus", hi);
  }, []);

  useEffect(() => { const f = () => api.state().then(setSt).catch(() => {}); f(); const t = setInterval(f, 3000); return () => clearInterval(t); }, []);
  useEffect(() => {
    if (showIdx === null) return;
    const t = setTimeout(() => setShowIdx((i) => (i === null || i + 1 >= STATES.length ? null : i + 1)), 2200);
    return () => clearTimeout(t);
  }, [showIdx]);
  const connected = st?.pets.find((p) => p.link === "connected");

  // ---- layers ----
  const objs = (cv.current?.getObjects() ?? []).slice().reverse();
  const act = (o: FabricObject) => { setTool("select"); cv.current!.setActiveObject(o); cv.current!.requestRenderAll(); setRev((r) => r + 1); };
  const toggle = (o: FabricObject, k: "visible" | "locked") => {
    if (k === "visible") o.set({ visible: !o.visible });
    else { const l = !(o as any).locked; (o as any).locked = l; o.set({ selectable: !l && toolRef.current === "select", evented: !l }); }
    cv.current!.requestRenderAll(); setRev((r) => r + 1);
  };
  const move = (o: FabricObject, up: boolean) => { const c = cv.current!; up ? c.bringObjectForward(o) : c.sendObjectBackwards(o); c.fire("object:modified", { target: o } as any); };
  const prev = fi > 0 ? frames[state][fi - 1]?.png : null;
  void rev;

  const drawnStates = STATES.filter((x) => frames[x].some((f) => f.png));
  const showState = showIdx !== null ? STATES[showIdx % STATES.length] : null;
  const showUrl = showState && pack ? pack.files.find((f: any) => f.name === `${showState}.gif`)?.url : null;
  const petPng = frames[state][fi]?.png;
  // the next step, one yellow band (signage raise): what moves this character toward the pet now
  const next = !frames.idle[0]?.png && !(state === "idle" && fi === 0 && objs.length)
    ? { text: "Draw or drop the character into idle, frame 1: every state starts from it", act: null as null | (() => void) }
    : !pack || pack.name !== name ? { text: `Make the sprite: seven states from what is on the sheet`, act: create }
    : connected ? { text: `Put ${pack.name} on ${connected.name}`, act: send }
    : { text: "Turn a pet on: OraclePet links it, then send", act: null };

  return (
    <div className="flex min-h-screen flex-col gap-3 p-3 lg:h-screen">
      {/* top: the seven states as words, the canvas id, the pet */}
      <header className="sticker flex flex-wrap items-center gap-x-5 gap-y-2 px-5 py-2.5">
        <div className="flex items-baseline gap-2">
          <h1 className="m-0 text-[15px] font-extrabold" style={{ fontStretch: "118%" }}>Pet Studio</h1>
          <span className="label">canvas <span className="text-ink">{CANVAS_ID}</span></span>
        </div>
        <nav className="flex flex-wrap items-baseline gap-x-4 gap-y-1" aria-label="pet states">
          {STATES.map((x) => (
            <button key={x} onClick={() => goto(x, 0)} title={HINT[x]} aria-current={state === x ? "page" : undefined}
              className={`relative cursor-pointer pb-1 text-[22px] leading-none font-bold lowercase transition-colors duration-150 ${state === x ? "text-ink" : "text-ink-3 hover:text-ink-2"}`}
              style={{ fontStretch: state === x ? "125%" : "100%" }}>
              {x}
              {frames[x].some((f) => f.png) && <span className="absolute -top-0.5 -right-2 size-1.5 rounded-full bg-cyan" />}
              {state === x && <span className="absolute inset-x-0 -bottom-0.5 border-b-2 border-dashed border-cut" />}
            </button>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-3">
          <span className={`flex items-center gap-1.5 text-[12px] ${connected ? "text-ink" : "text-ink-3"}`}>
            <span className={`size-2 rounded-full ${connected ? "bg-cyan" : "bg-liner-ink"}`} />
            {connected ? connected.name : "no pet linked"}
          </span>
          <a href="/" className="label underline decoration-dashed underline-offset-4 hover:text-ink">studio v1</a>
        </div>
      </header>

      {/* the next step: one yellow band */}
      <div className="flex items-center gap-3 rounded-[10px] bg-yellow px-4 py-2 text-[13px] font-semibold text-ink" role="status">
        <span className="label !text-ink">next</span>
        <span className="flex-1">{next.text}</span>
        {next.act && <button className="btn h-7 border-ink bg-ink text-white hover:enabled:bg-ink-2" onClick={next.act}>Do it</button>}
      </div>
      {err && <div className="cursor-pointer rounded-[10px] border border-bad bg-white px-4 py-2 text-[13px] text-bad" role="alert" onClick={() => setErr("")}>{err} <span className="text-ink-3">· dismiss</span></div>}

      <div className="flex min-h-0 flex-1 flex-col gap-3 lg:flex-row">
        {/* tools: a vertical sticker strip */}
        <aside className="sticker flex flex-wrap items-center justify-center gap-1 px-2 py-2 lg:w-[60px] lg:flex-col lg:flex-nowrap lg:py-3" aria-label="tools">
          {TOOLS.map((t) => (
            <button key={t.id} className="tool" aria-pressed={tool === t.id} title={`${t.label} (${t.key.toUpperCase()})`} aria-label={t.label} onClick={() => setTool(t.id)}>
              <t.icon size={18} strokeWidth={1.75} />
            </button>
          ))}
          <label className="tool" title="Place a picture (or paste with Cmd-V, or drop it on the sheet)" aria-label="Place a picture">
            <ImagePlus size={18} strokeWidth={1.75} />
            <input type="file" accept="image/*" className="hidden" onChange={async (e) => { const f = e.target.files?.[0]; if (f) guard(() => place(f).then(() => {})); e.target.value = ""; }} />
          </label>
          <div className="my-2 h-px w-7 bg-liner-ink" />
          <button className="tool" title="Undo (Cmd-Z)" aria-label="Undo" onClick={undo}><Undo2 size={17} strokeWidth={1.75} /></button>
          <button className="tool" title="Redo (Shift-Cmd-Z)" aria-label="Redo" onClick={redo}><Redo2 size={17} strokeWidth={1.75} /></button>
          <button className="tool" title="Delete the selection (Backspace)" aria-label="Delete selection" onClick={removeSelected}><Trash2 size={17} strokeWidth={1.75} /></button>
          <div className="mt-auto hidden flex-col items-center gap-1 lg:flex">
            <span className="label">size</span>
            <span className="text-[12px] font-semibold tabular-nums">{size}</span>
          </div>
        </aside>

        {/* the sheet: the artboard as a big sticker with crop and registration marks */}
        <main className="flex min-w-0 flex-1 flex-col items-center justify-center gap-4 overflow-auto"
          onDragOver={(e) => e.preventDefault()}
          onDrop={async (e) => { e.preventDefault(); const f = [...e.dataTransfer.files].find((x) => x.type.startsWith("image/") || x.name.endsWith(".svg")); if (f) guard(() => place(f).then(() => {})); }}>
          <div className="relative p-7">
            {[["left-0 top-0", ""], ["right-0 top-0", "scale-x-[-1]"], ["left-0 bottom-0", "scale-y-[-1]"], ["right-0 bottom-0", "scale-[-1]"]].map(([pos, flip]) => (
              <svg key={pos} className={`reg ${pos} ${flip}`} viewBox="0 0 20 20" aria-hidden>
                <path d="M0 12H8M12 0V8" stroke="#16181d" strokeWidth="1" />
                <circle cx="12" cy="12" r="4" fill="none" stroke="#16181d" strokeWidth="1" />
                <path d="M12 7v10M7 12h10" stroke="#16181d" strokeWidth="1" />
              </svg>
            ))}
            <div className="sticker relative overflow-hidden !rounded-[18px]" style={{ width: W * zoom, height: H * zoom,
              backgroundImage: "conic-gradient(#f1f3f6 25%, #ffffff 0 50%, #f1f3f6 0 75%, #ffffff 0)", backgroundSize: `${16 * zoom}px ${16 * zoom}px` }}>
              {/* always mounted: fabric moves the <canvas> into its own wrapper, so React must never
                  insert a sibling before it (that was an insertBefore crash on frame 2) */}
              <img src={onion && prev ? prev : undefined} alt="" className={`pointer-events-none absolute inset-0 size-full opacity-25 ${onion && prev ? "" : "hidden"}`} />
              <div className="absolute inset-0"><canvas ref={el} /></div>
            </div>
          </div>
          <div className="sticker flex items-center gap-4 px-4 py-2">
            <div className="flex gap-1" role="group" aria-label="colours">
              {SWATCHES.map((c) => (
                <button key={c} onClick={() => recolor(c)} title={c} aria-label={`colour ${c}`}
                  className={`size-6 cursor-pointer rounded-md border transition-transform duration-150 hover:-translate-y-0.5 ${color === c ? "border-ink ring-2 ring-cut ring-offset-1" : "border-liner-ink"}`}
                  style={{ background: c }} />
              ))}
              <label className="relative size-6 cursor-pointer overflow-hidden rounded-md border border-liner-ink" title="any colour" aria-label="any colour"
                style={{ background: "conic-gradient(red, yellow, lime, cyan, blue, magenta, red)" }}>
                <input type="color" value={color} onChange={(e) => recolor(e.target.value)} className="absolute inset-0 cursor-pointer opacity-0" />
              </label>
            </div>
            <div className="h-6 w-px bg-liner-ink" />
            <label className="flex items-center gap-2"><span className="label">brush</span>
              <input type="range" min={2} max={60} value={size} onChange={(e) => setSize(+e.target.value)} className="w-24" /></label>
            <label className="flex items-center gap-2"><span className="label">zoom</span>
              <input type="range" min={0.5} max={2.5} step={0.25} value={zoom} onChange={(e) => setZoom(+e.target.value)} className="w-20" />
              <span className="w-8 text-[12px] tabular-nums">{zoom}×</span></label>
            <label className="flex items-center gap-1.5"><input type="checkbox" checked={onion} onChange={(e) => setOnion(e.target.checked)} /><span className="label">onion skin</span></label>
          </div>
        </main>

        {/* right: on the pet, layers, picture, sprite */}
        <aside className="flex w-full flex-col gap-3 pr-1 pb-1 lg:w-[300px] lg:overflow-y-auto">
          <section className="sticker p-4">
            <div className="mb-3 flex items-baseline justify-between">
              <h2 className="m-0 text-[13px] font-bold">On the pet</h2>
              <span className="label">96 × 100 · {showState ? `sprite: ${showState}` : `${state} ${fi + 1}`}</span>
            </div>
            <div className="relative mx-auto grid h-[208px] w-[200px] place-items-center rounded-[10px] bg-ink ring-4 ring-[#2a2d33]">
              {showUrl ? <img key={showUrl} src={`${showUrl}?t=${pack.bytes}`} alt={`${showState} state of ${pack.name}`} className="h-[200px] w-[192px] object-contain [image-rendering:pixelated]" />
                : petPng ? <img src={petPng} alt={`${state} frame ${fi + 1} as the pet shows it`} className="h-[200px] w-[192px] object-contain [image-rendering:pixelated]" style={{ filter: "contrast(1.02)" }} />
                : <span className="label !text-[#8b93a3]">empty frame</span>}
              {showState && <span className="absolute bottom-1.5 left-2 text-[11px] font-bold lowercase text-white/80" style={{ fontStretch: "120%" }}>{showState}</span>}
            </div>
            {pack && (
              <button className="btn mt-3 w-full" onClick={() => setShowIdx((i) => (i === null ? 0 : null))}>
                {showIdx === null ? <><Play size={14} /> Play the sprite, all seven states</> : <><Pause size={14} /> Stop</>}
              </button>
            )}
          </section>

          <section className="sticker p-4">
            <div className="mb-2 flex items-baseline justify-between">
              <h2 className="m-0 text-[13px] font-bold">Layers</h2>
              <span className="label">{objs.length || "none"}</span>
            </div>
            {!objs.length && <p className="m-0 text-[12px] text-ink-3">Draw, drop a picture, or ask an agent: it all lands here.</p>}
            <ul className="m-0 max-h-[232px] list-none space-y-0.5 overflow-y-auto p-0">
              {objs.map((o, i) => (
                <li key={i} data-layer={label(o)} aria-label={`layer ${label(o)}`} onClick={() => act(o)}
                  className={`group flex cursor-pointer items-center gap-1 rounded-lg py-1 pr-1 pl-2 text-[12.5px] transition-colors duration-150 ${active === o ? "bg-[#fde6f1] text-ink outline outline-1 outline-dashed outline-cut" : "hover:bg-liner"}`}>
                  <span className={`flex-1 truncate ${o.visible ? "" : "text-ink-3 line-through"}`}>{label(o)}</span>
                  <button className="icon-btn opacity-0 group-hover:opacity-100" title="up" aria-label="move up" onClick={(e) => { e.stopPropagation(); move(o, true); }}><ChevronUp size={14} /></button>
                  <button className="icon-btn opacity-0 group-hover:opacity-100" title="down" aria-label="move down" onClick={(e) => { e.stopPropagation(); move(o, false); }}><ChevronDown size={14} /></button>
                  <button className="icon-btn" title={o.visible ? "hide" : "show"} aria-label={o.visible ? "hide" : "show"} onClick={(e) => { e.stopPropagation(); toggle(o, "visible"); }}>{o.visible ? <Eye size={14} /> : <EyeOff size={14} />}</button>
                  <button className="icon-btn" title={(o as any).locked ? "unlock" : "lock"} aria-label={(o as any).locked ? "unlock" : "lock"} onClick={(e) => { e.stopPropagation(); toggle(o, "locked"); }}>{(o as any).locked ? <Lock size={14} /> : <LockOpen size={14} />}</button>
                </li>
              ))}
            </ul>
            {active && (
              <div className="mt-3 space-y-2 border-t border-dashed border-liner-ink pt-3">
                <label className="flex items-center gap-2"><span className="label w-12">opacity</span>
                  <input type="range" min={0} max={1} step={0.05} value={active.opacity ?? 1} className="flex-1"
                    onChange={(e) => { active.set({ opacity: +e.target.value }); cv.current!.requestRenderAll(); setRev((r) => r + 1); }} /></label>
                {active instanceof FabricImage && <button className="btn w-full" onClick={() => guard(removeBackground)}><Scissors size={14} /> Cut out the background</button>}
              </div>
            )}
          </section>

          <section className="sticker p-4">
            <h2 className="m-0 mb-2 text-[13px] font-bold">Draw me a picture</h2>
            <textarea className="field h-16 resize-none py-1.5" value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="a tiny green dragon with a party hat" />
            <button className="btn mt-2 w-full" disabled={!prompt} onClick={generate}><Sparkles size={14} /> Codex draws it into this frame</button>
            <p className="m-0 mt-1.5 text-[11.5px] text-ink-3">Takes 2–4 minutes; the background comes out cut.</p>
          </section>

          <section className="sticker p-4">
            <h2 className="m-0 mb-1 text-[13px] font-bold">One picture, every pose</h2>
            <p className="m-0 text-[11.5px] text-ink-3">Idle frame 1 is the picture. The AI redraws the character in 14 poses, checks them against it, redraws what is off, and fills every state's frames. 4–10 minutes.</p>
            <button className="btn btn-cut mt-2 w-full" onClick={() => guard(async () => { await doAuto(name); })}><Sparkles size={14} /> AI makes the whole sprite</button>
            {auto && (
              <div className="mt-2">
                <img src={`${auto.contact}?t=${auto.bytes}`} alt="the redrawn frames, as the pet shows them" className="w-full rounded-md bg-ink" />
                <ul className="m-0 mt-1 list-none p-0 text-[11.5px] text-ink-3">
                  {auto.reviews?.map((v: any) => <li key={v.round}>check {v.round}: {v.ok ? "every state passes" : `redrew ${v.bad.join(", ")}`}{v.notes && !v.ok ? ` (${v.notes})` : ""}</li>)}
                </ul>
                <a className="text-[11.5px] text-cyan" href={auto.sheet} target="_blank" rel="noreferrer">the sheet it drew</a>
              </div>
            )}
          </section>

          <section className="sticker p-4">
            <h2 className="m-0 mb-2 text-[13px] font-bold">Sprite</h2>
            <label className="label mb-1 block">pack name</label>
            <input className="field" value={name} onChange={(e) => setName(e.target.value.toLowerCase())} placeholder="pack name" />
            <p className="m-0 mt-2 text-[11.5px] text-ink-3">{drawnStates.length ? `Drawn: ${drawnStates.join(", ")}. The other states come from idle frame 1.` : "Idle frame 1 makes all seven states; draw a state to make it your own."}</p>
            <button className="btn btn-cut mt-3 w-full" onClick={create}>Make the sprite</button>
            {job && (
              <div className="mt-3 text-[12px]" aria-live="polite">
                <div className="flex items-center gap-2">
                  <span className={`size-2 rounded-full ${job.status === "ok" ? "bg-ok" : job.status === "failed" ? "bg-bad" : "animate-pulse bg-cut"}`} />
                  <span className="flex-1 truncate font-medium">{job.title}</span>
                  <span className="label">{job.status}</span>
                </div>
                {(job.progress !== undefined || job.status === "running") && (
                  <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-liner">
                    <div className={`h-full rounded-full bg-cut transition-[width] duration-300 ${job.progress === undefined ? "w-1/3 animate-pulse" : ""}`} style={job.progress !== undefined ? { width: `${job.progress}%` } : undefined} />
                  </div>
                )}
                <div className={`mt-1 truncate ${job.status === "failed" ? "text-bad" : "text-ink-3"}`}>{job.error ?? job.log?.at(-1)}</div>
              </div>
            )}
            {pack && (
              <>
                <div className="mt-3 grid grid-cols-4 gap-2">
                  {pack.files.filter((f: any) => f.name.endsWith(".gif")).map((f: any) => (
                    <figure key={f.name} className="m-0 text-center">
                      <img src={`${f.url}?t=${pack.bytes}`} alt={`${f.name.replace(".gif", "")} state`} className="aspect-[96/100] w-full rounded-md bg-ink [image-rendering:pixelated]" />
                      <figcaption className="mt-0.5 text-[10.5px] text-ink-3">{f.name.replace(".gif", "")}</figcaption>
                    </figure>
                  ))}
                </div>
                <button className="btn btn-cut mt-3 w-full" disabled={!connected} onClick={send}><Send size={14} /> {connected ? `Send to ${connected.name}` : "No pet linked"}</button>
              </>
            )}
          </section>
        </aside>
      </div>

      {/* frames: a strip of small stickers for the current state */}
      <footer className="sticker flex flex-wrap items-center gap-4 px-4 py-2.5" aria-label={`${state} frames`}>
        <div className="w-24">
          <div className="text-[15px] leading-none font-bold lowercase" style={{ fontStretch: "120%" }}>{state}</div>
          <div className="label mt-1">frame {fi + 1} of {frames[state].length}</div>
        </div>
        <div className="flex flex-1 items-center gap-2.5 overflow-x-auto py-1.5 pl-1">
          {frames[state].map((f, i) => (
            <button key={i} onClick={() => goto(state, i)} aria-label={`frame ${i + 1}`} aria-current={i === fi ? "true" : undefined}
              className={`sticker relative h-[64px] w-[62px] shrink-0 cursor-pointer overflow-hidden !rounded-[10px] transition-transform duration-150 ${i === fi ? "sticker-lift -translate-y-1 -rotate-2 outline-2 outline-offset-2 outline-dashed outline-cut" : "hover:-translate-y-0.5"}`}>
              {f.png ? <img src={f.png} alt="" className="size-full object-contain" /> : <span className="label">empty</span>}
              <span className="absolute bottom-0.5 left-1.5 text-[10px] font-bold tabular-nums text-ink-2">{i + 1}</span>
            </button>
          ))}
          <div className="ml-1 flex gap-1">
            <button className="icon-btn size-8" title="New empty frame" aria-label="new frame" onClick={() => addFrame(false)}><Plus size={16} /></button>
            <button className="icon-btn size-8" title="Duplicate this frame" aria-label="duplicate frame" onClick={() => addFrame(true)}><Copy size={15} /></button>
            <button className="icon-btn size-8" title="Delete this frame" aria-label="delete frame" onClick={deleteFrame}><X size={16} /></button>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="grid h-[52px] w-[50px] place-items-center overflow-hidden rounded-md bg-ink" aria-label="playback">
            {playing && playFrames.length ? <img src={playFrames[playIdx % playFrames.length]} alt="" className="size-full object-contain" /> : null}
          </div>
          <button className="btn" onClick={() => setPlaying((p) => !p)}>{playing ? <><Pause size={14} /> Stop</> : <><Play size={14} /> Play</>}</button>
          <label className="flex items-center gap-1.5"><span className="label">fps</span>
            <input type="number" min={1} max={20} value={fps} onChange={(e) => setFps(+e.target.value || 8)} className="field h-7 w-12 px-1.5 text-center tabular-nums" /></label>
        </div>
      </footer>
    </div>
  );
}
