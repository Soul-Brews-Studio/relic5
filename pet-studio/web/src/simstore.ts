// One simulator for the whole page: the App and Blocks tabs show it, and the agent drives it
// (live.ts: "simulate", "tap") and looks at it (snapshot() -> PNG, posted to the server).
import { useEffect, useState } from "react";
import { PetSim, STATE_GIF, type SimView } from "./sim";

let sim: PetSim | null = null;
let view: SimView | null = null;
let app = "";
let packs: string[] = [];
const listeners = new Set<() => void>();
const changed = () => listeners.forEach((f) => f());

export function setPacks(p: string[]) { packs = p; }
export function simApp() { return app; }
export function currentView() { return view; }
export function simCanvas() { return sim?.cv ?? null; }

export async function simulate(name: string, pack?: string) {
  const bytes = await (await fetch(`/api/apps/${name}.wasm?t=${Date.now()}`)).arrayBuffer();
  sim?.stop();
  const s = new PetSim(pack ?? view?.pack ?? "siamese", (v) => { view = v; changed(); }, packs);
  sim = s;
  app = name;
  view = s.view;
  await s.load(bytes);
  changed();
}
export function tap(x: number, y: number) { sim?.tap(x, y); }
export function setPack(p: string) { if (sim && view) { sim.view = { ...view, pack: p }; view = sim.view; changed(); } }

export function useSim(): SimView | null {
  const [, force] = useState(0);
  useEffect(() => { const f = () => force((n) => n + 1); listeners.add(f); return () => { listeners.delete(f); }; }, []);
  return view;
}

/** The sim screen as the pet would draw it (320x480): the GIF frame now playing, caption, HUD. */
export function snapshot(): string | null {
  if (!view) return null;
  const img = document.querySelector<HTMLImageElement>(".screen .petgif");
  const c = document.createElement("canvas");
  c.width = 320; c.height = 480;
  const g = c.getContext("2d")!;
  g.fillStyle = "#000"; g.fillRect(0, 0, 320, 480);
  g.imageSmoothingEnabled = false;
  if (view.canvas && sim) g.drawImage(sim.cv, 0, 0);
  else if (img && img.complete && img.naturalWidth) g.drawImage(img, 16, 30, 288, 300);
  g.fillStyle = "#fff"; g.font = "600 20px ui-monospace, Menlo, monospace"; g.textAlign = "center";
  if (!view.canvas) g.fillText(view.caption, 160, 350);
  g.strokeStyle = "#333"; g.beginPath(); g.moveTo(0, 400); g.lineTo(320, 400); g.stroke();
  g.fillStyle = "#ccc"; g.font = "16px ui-monospace, Menlo, monospace"; g.textAlign = "left";
  g.fillText(view.status, 10, 428);
  return c.toDataURL("image/png");
}

export const gifFor = (v: SimView) => `/api/packs/${v.pack}/${v.heartUntil > performance.now() ? "heart" : STATE_GIF[v.state]}.gif`;
