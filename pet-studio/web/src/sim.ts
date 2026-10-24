// The pet app ABI (lab/pet-sdk/pet.h) in the browser: run a built .wasm before it goes to the pet.
// Same imports the firmware's WAMR host gives (main/petapp.c): show, react, caption, status, pack,
// sound, millis, log, tone, play, say. on_tick every 100 ms, on_tap on a click, as on the pet.

export type SimView = {
  state: number;            // PET_IDLE 0, BUSY 1, ATTENTION 2, SLEEP 3
  heartUntil: number;
  caption: string;
  status: string;
  pack: string;
  log: string[];
  canvas: boolean;          // canvas mode: the app draws the screen (PetSim.cv), not the cat
  frame: number;            // bumps each time a callback finished drawing
};
export const CANVAS_W = 320, CANVAS_H = 400;   // the 3.5in boards: the area above the HUD
/** RGB565 -> CSS colour. */
export const css565 = (c: number) => `rgb(${((c >> 11) & 31) * 255 / 31 | 0},${((c >> 5) & 63) * 255 / 63 | 0},${(c & 31) * 255 / 31 | 0})`;
export const STATE_GIF = ["idle", "busy", "attention", "sleep"];

export class PetSim {
  view: SimView;
  private mem?: WebAssembly.Memory;
  private ex: Record<string, any> = {};
  private t0 = performance.now();
  private timer?: number;
  private audio?: AudioContext;
  private drew = false;
  readonly cv: HTMLCanvasElement = Object.assign(document.createElement("canvas"), { width: CANVAS_W, height: CANVAS_H });
  private g = this.cv.getContext("2d")!;

  constructor(pack: string, private onChange: (v: SimView) => void, private packs: string[]) {
    this.view = { state: 0, heartUntil: 0, caption: "", status: "", pack, log: [], canvas: false, frame: 0 };
  }

  private str(ptr: number, len: number) {
    return new TextDecoder().decode(new Uint8Array(this.mem!.buffer, ptr, len));
  }
  private set(p: Partial<SimView>) { this.view = { ...this.view, ...p }; this.onChange(this.view); }
  private log(line: string) { this.set({ log: [...this.view.log.slice(-40), line] }); }

  private beep(hz: number, ms: number) {
    this.audio ??= new AudioContext();
    const o = this.audio.createOscillator(), g = this.audio.createGain();
    o.frequency.value = Math.max(50, Math.min(8000, hz));
    g.gain.value = 0.08;
    o.connect(g).connect(this.audio.destination);
    o.start(); o.stop(this.audio.currentTime + Math.max(10, Math.min(2000, ms)) / 1000);
  }

  async load(bytes: ArrayBuffer) {
    const pet: Record<string, Function> = {
      show: (s: number) => this.set({ state: s >= 0 && s <= 3 ? s : 0 }),
      react: () => this.set({ heartUntil: performance.now() + 1500 }),
      caption: (p: number, n: number) => this.set({ caption: this.str(p, n).slice(0, 20) }),
      status: (p: number, n: number) => this.set({ status: this.str(p, n) }),
      pack: (p: number, n: number) => { const s = this.str(p, n); if (!this.packs.includes(s)) return 0; this.set({ pack: s }); return 1; },
      sound: (k: number) => k === 0 ? (this.beep(320, 120), setTimeout(() => this.beep(240, 160), 140)) : this.beep(k === 1 ? 1200 : 600, 60),
      millis: () => Math.floor(performance.now() - this.t0),
      log: (p: number, n: number) => this.log(this.str(p, n)),
      tone: (hz: number, ms: number) => this.beep(hz, ms),
      play: (p: number, n: number) => { this.log(`play ${this.str(p, n)} (clip; silent here)`); return 1; },
      canvas: (on: number) => {
        if (on && !this.view.canvas) { this.g.fillStyle = "#000"; this.g.fillRect(0, 0, CANVAS_W, CANVAS_H); }
        this.set({ canvas: !!on });
      },
      clear: (c: number) => { this.draw(); this.g.fillStyle = css565(c); this.g.fillRect(0, 0, CANVAS_W, CANVAS_H); },
      rect: (x: number, y: number, w: number, h: number, c: number) => { this.draw(); this.g.fillStyle = css565(c); this.g.fillRect(x, y, w, h); },
      circle: (x: number, y: number, r: number, c: number) => {
        this.draw(); this.g.fillStyle = css565(c); this.g.beginPath(); this.g.arc(x, y, Math.max(0, r), 0, Math.PI * 2); this.g.fill();
      },
      line: (x0: number, y0: number, x1: number, y1: number, c: number) => {
        this.draw(); this.g.strokeStyle = css565(c); this.g.lineWidth = 1;
        this.g.beginPath(); this.g.moveTo(x0 + 0.5, y0 + 0.5); this.g.lineTo(x1 + 0.5, y1 + 0.5); this.g.stroke();
      },
      text: (x: number, y: number, scale: number, c: number, p: number, n: number) => {
        this.draw(); const s = Math.max(1, Math.min(8, scale));
        this.g.fillStyle = css565(c); this.g.font = `bold ${8 * s}px ui-monospace, Menlo, monospace`; this.g.textBaseline = "top";
        this.g.fillText(this.str(p, n), x, y);
      },
      width: () => CANVAS_W,
      height: () => CANVAS_H,
      say: (p: number, n: number) => {
        const t = this.str(p, n);
        this.log(`say "${t}"`);
        try { speechSynthesis.speak(new SpeechSynthesisUtterance(t)); } catch {}
        return 1;
      },
    };
    // anything else the module imports from "pet" (e.g. AssemblyScript's abort) is a no-op here
    const imports = new Proxy(pet, { get: (o, k: string) => o[k] ?? ((...a: any[]) => { this.log(`pet.${k}(${a.join(", ")})`); return 0; }) });
    const { instance } = await WebAssembly.instantiate(bytes, { pet: imports as any });
    this.ex = instance.exports;
    this.mem = instance.exports.memory as WebAssembly.Memory;
    this.t0 = performance.now();
    this.cb("on_start");
    this.timer = window.setInterval(() => this.cb("on_tick", Math.floor(performance.now() - this.t0)), 100);
    this.log(`loaded: exports ${Object.keys(this.ex).join(", ")}`);
  }

  private draw() { if (this.view.canvas) this.drew = true; }
  /** One callback, like the firmware's call(): a canvas frame is shown when the callback ends. */
  private cb(name: string, ...args: number[]) {
    if (!this.ex[name]) return;
    try { this.ex[name](...args); }
    catch (e) { this.log(`${name} trapped: ${e}`); this.stop(); return; }
    if (this.drew) { this.drew = false; this.set({ frame: this.view.frame + 1 }); }
  }

  tap(x: number, y: number) {
    if (this.ex.on_tap) this.cb("on_tap", x, y);
    else this.set({ heartUntil: performance.now() + 1500 });   // the firmware's default: the heart
  }

  fleet(total: number, running: number, waiting: number) { this.cb("on_fleet", total, running, waiting); }
  stop() { if (this.timer) clearInterval(this.timer); }
}
