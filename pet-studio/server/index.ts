// pet-studio server: one local HTTP API for making things for the desk pet and putting them on it.
//
//   bun server/index.ts          -> http://127.0.0.1:4810  (the API, and the built frontend from dist/)
//
// It drives the tools that already exist in this lab, nothing new underneath:
//   apps      lab/pet-sdk/build.sh        C / Zig / Rust / AssemblyScript -> .wasm (+ the pet's WAMR load check)
//   packs     tools/make-pack.sh          one picture -> the seven state GIFs; or Codex image_gen first
//   firmware  lab/jc3248-pet-idf          idf.py for jc3248, lcd28 or sc01
//   BLE       OraclePet.app               deskpet:// URLs; it holds the pets' Bluetooth links and writes
//                                         /tmp/deskpet-status.json (macOS denies Bluetooth to a bare process)
//   USB       idf.py flash                bootloader, partition table, app and packs
//
// Every slow thing is a job: POST returns {job}, GET /api/jobs/:id has its log and result.
// Binds 127.0.0.1 only: it runs builds and flashes boards, so it is not for the network.
import { appendFileSync, cpSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { basename, join, resolve, extname } from "node:path";
import { homedir, tmpdir } from "node:os";
import { blocksToC, EXAMPLE, SUPPORTED } from "../shared/petblocks";

const STUDIO = resolve(import.meta.dir, "..");
// The pet's own code (pet-sdk, the ESP-IDF firmware) lives in esp32-oracle's lab/. In esp32-oracle the studio sits
// inside that lab; in relic5 (pet-studio/, merged 2026-10-24) it does not, so PET_LAB names the lab, else the
// esp32-oracle checkout under ghq is used, else the studio's parent as before.
function labDir(): string {
  if (process.env.PET_LAB) return resolve(process.env.PET_LAB);
  const here = resolve(STUDIO, "..");
  if (existsSync(join(here, "pet-sdk"))) return here;
  const ghq = Bun.spawnSync(["ghq", "root"]).stdout.toString().trim() || join(process.env.HOME ?? "", "Code");
  const lab = join(ghq, "github.com/Soul-Brews-Studio/esp32-oracle/lab");
  return existsSync(join(lab, "pet-sdk")) ? lab : here;
}
const LAB = labDir();
const SDK = join(LAB, "pet-sdk");
const FW = join(LAB, "jc3248-pet-idf");
const WS = join(STUDIO, "workspace");
const DIST = join(STUDIO, "dist");
const STATUS = process.env.ORACLEPET_STATUS ?? "/tmp/deskpet-status.json";
const PORT = Number(process.env.PET_STUDIO_PORT ?? 4810);
const IDF = process.env.IDF_PATH_V6 ?? join(homedir(), "esp/esp-idf-v6");
for (const d of ["apps", "packs", "images", "designs", "canvases", "flasher"]) mkdirSync(join(WS, d), { recursive: true });

// ---- boards (lab/jc3248-pet-idf/main/board.h) ----
const BOARDS: Record<string, { label: string; project: string; dir: string; defs: string }> = {
  jc3248: { label: "JC3248W535 3.5in", project: "jc3248_pet_idf", dir: "build", defs: "" },
  lcd28: { label: "2.8in ILI9341", project: "oraclepet_lcd28", dir: "build-lcd28", defs: "-DPET_BOARD=lcd28 -DSDKCONFIG=build-lcd28/sdkconfig" },
  sc01: { label: "WT32-SC01 Plus", project: "oraclepet_sc01", dir: "build-sc01", defs: "-DPET_BOARD=sc01 -DSDKCONFIG=build-sc01/sdkconfig" },
};
const firmwareBin = (b: string) => join(FW, BOARDS[b].dir, `${BOARDS[b].project}.bin`);

const NAME = /^[a-z0-9_-]{1,23}$/;
const LANGS: Record<string, string> = { c: "c", zig: "zig", rust: "rs", rs: "rs", as: "ts", ts: "ts", assemblyscript: "ts" };

// ---- live: the open page and the agent share one workspace (blocks, code, simulator screen) ----
// The page sends what it has (POST /api/live/*, with its origin id); the agent's changes go out to
// every page over SSE (GET /api/live/events), the way droidcast mirrors a phone: the agent sees the
// screen (GET /api/live/screen.png) and taps it (POST /api/live/command {type: "tap"}).
const live = {
  rev: 0, name: "blocks", blocks: EXAMPLE as object, c: "" as string,
  code: null as null | { name: string; lang: string; source: string },
  sim: null as any, screen: null as null | { png: Uint8Array; at: number },
};
try { live.c = blocksToC(live.blocks, live.name); } catch {}
const subs = new Set<ReadableStreamDefaultController<Uint8Array>>();
// Pages listen on a WebSocket (/api/live/ws). An SSE stream holds one of the browser's six HTTP
// connections to this host, so a seventh canvas tab could not load and every page's result POST
// queued behind the streams (round 3: every call timed out). SSE stays for older pages.
type WsData = { origin: string };
const wsSubs = new Set<import("bun").ServerWebSocket<WsData>>();
const pageCount = () => subs.size + wsSubs.size;
function dropOrigin(origin: string) { if (origin) for (const [cv, d] of designers) if (d.origin === origin) designers.delete(cv); }
function push(ev: Record<string, unknown>) {
  const text = JSON.stringify(ev);
  for (const w of wsSubs) { try { w.send(text); } catch { wsSubs.delete(w); } }
  const line = new TextEncoder().encode(`data: ${JSON.stringify(ev)}\n\n`);
  for (const c of subs) { try { c.enqueue(line); } catch { subs.delete(c); } }
}
// Calls into a page (studio v2's designer): the server sends {type: "call", id, to, action, args}
// over SSE to ONE page, the one showing that canvas that said hello last, which runs the action and
// posts the result to /api/live/result. MCP tools and the canvas CLI wait on that.
// A canvas is a named design (/v2?canvas=<id>); several agents (Claude, Codex, omx) can each draw
// on their own canvas, or on one together, and every change carries who made it.
const designers = new Map<string, { origin: string; at: number }>();
const CANVAS = /^[a-z0-9_-]{1,32}$/;
const pending = new Map<string, (r: { ok: boolean; result?: unknown; error?: string }) => void>();
/** No page shows that canvas: open one in ego-browser's own "Pet Studio canvases" space (Nat's
 * browser rule: agents' pages live in ego, never in his window) and wait for its hello. */
async function openCanvasPage(canvas: string) {
  const url = `http://127.0.0.1:${PORT}/v2?canvas=${canvas}`;
  const script = `const t = await taskSpace("Pet Studio canvases");
const tabs = await t.tabs();
const have = tabs.find((x) => x.url === ${JSON.stringify(url)});
if (!have) { const p = tabs.length === 1 && tabs[0].url === "about:blank" ? t.page("p1") : await t.newPage(); await p.goto(${JSON.stringify(url)}); }
console.log("opened");`;
  try {
    const p = Bun.spawn(["ego-browser", "nodejs"], { stdin: new Blob([script]), stdout: "pipe", stderr: "pipe" });
    await Promise.race([p.exited, Bun.sleep(20000)]);
  } catch {}
  for (let t = 0; t < 40 && !designers.has(canvas); t++) await Bun.sleep(250);
}

async function callPage(action: string, args: unknown, timeoutMs = 20000, canvas = "main", by = "agent") {
  if (!designers.has(canvas)) await openCanvasPage(canvas);
  const designer = designers.get(canvas);
  if (!designer || !pageCount()) {
    throw new Error(`canvas "${canvas}" is not open in a browser: open http://127.0.0.1:${PORT}/v2?canvas=${canvas}` +
      (designers.size ? ` (open now: ${[...designers.keys()].join(", ")})` : ""));
  }
  const id = `c${Date.now().toString(36)}${++seq}`;
  const answer = new Promise<{ ok: boolean; result?: unknown; error?: string }>((ok) => {
    pending.set(id, ok);
    setTimeout(() => { if (pending.delete(id)) ok({ ok: false, error: `the page did not answer ${action} within ${timeoutMs / 1000} s` }); }, timeoutMs);
  });
  push({ type: "call", id, to: designer.origin, action, args, by, origin: "agent" });
  const r = await answer;
  if (!r.ok) throw new Error(r.error ?? `${action} failed`);
  return r.result;
}

const liveSummary = () => ({ rev: live.rev, name: live.name, pages: pageCount(), blocks: live.blocks, c: live.c, code: live.code,
  sim: live.sim, screenAt: live.screen?.at ?? null });

// ---- jobs ----
type Job = {
  id: string; kind: string; title: string; status: "queued" | "running" | "ok" | "failed";
  started: number; ended?: number; log: string[]; result?: any; error?: string;
  progress?: number; waitingFor?: string;   // 0..100 when the tool reports it; the job ahead in the lane
};
const jobs = new Map<string, Job>();
const lanes = new Map<string, Promise<void>>();   // one at a time per lane: "idf" (builds, USB), "ble", "sdk", "pack"
let seq = 0;

function job(kind: string, title: string, lane: string, work: (j: Job) => Promise<any>): Job {
  const j: Job = { id: `${Date.now().toString(36)}-${++seq}`, kind, title, status: "queued", started: Date.now(), log: [] };
  jobs.set(j.id, j);
  const prev = lanes.get(lane) ?? Promise.resolve();
  const ahead = [...jobs.values()].filter((x) => x !== j && x.kind === kind && (x.status === "running" || x.status === "queued")).at(-1);
  if (ahead) j.waitingFor = ahead.title;
  const run = prev.then(async () => {
    j.status = "running";
    j.waitingFor = undefined;
    try { j.result = await work(j); j.status = "ok"; }
    catch (e: any) { j.status = "failed"; j.error = String(e?.message ?? e); j.log.push(`❌ ${j.error}`); }
    j.ended = Date.now();
  });
  lanes.set(lane, run.catch(() => {}));
  if (jobs.size > 200) jobs.delete(jobs.keys().next().value!);
  return j;
}

const strip = (s: string) => s.replace(/\x1b\[[0-9;]*[A-Za-z]/g, "").replace(/\r/g, "");

/** Run a command, streaming its lines into the job log. Throws on a non-zero exit. */
async function sh(j: Job, cmd: string[], opts: { cwd?: string; env?: Record<string, string> } = {}) {
  j.log.push(`$ ${cmd.join(" ").slice(0, 300)}`);
  const p = Bun.spawn(cmd, { cwd: opts.cwd, env: { ...process.env, ...opts.env }, stdout: "pipe", stderr: "pipe" });
  const pump = async (s: ReadableStream<Uint8Array>) => {
    const dec = new TextDecoder(); let buf = "";
    const rd = s.getReader();
    for (let r = await rd.read(); !r.done; r = await rd.read()) {
      buf += dec.decode(r.value, { stream: true });
      const lines = buf.split("\n"); buf = lines.pop() ?? "";
      for (const l of lines) { const t = strip(l); if (t.trim()) j.log.push(t); }
      if (j.log.length > 3000) j.log.splice(0, j.log.length - 3000);
    }
    if (buf.trim()) j.log.push(strip(buf));
  };
  await Promise.all([pump(p.stdout), pump(p.stderr)]);
  const rc = await p.exited;
  if (rc !== 0) throw new Error(`${basename(cmd[0])} exited with ${rc}`);
}

/** zsh with ESP-IDF v6 exported. ~/esp/pyshim puts python3.13 first (IDF's venv is py3.13). */
const idf = (j: Job, script: string) =>
  sh(j, ["/bin/zsh", "-c", `export PATH="$HOME/esp/pyshim:$PATH"; . "${IDF}/export.sh" >/dev/null || exit 9; ${script}`], { cwd: FW });

// ---- wasm: what a module imports and exports (enough to check it against the pet ABI) ----
function wasmInfo(buf: Uint8Array) {
  if (buf.length < 8 || buf[0] !== 0 || buf[1] !== 0x61 || buf[2] !== 0x73 || buf[3] !== 0x6d) return null;
  let i = 8;
  const leb = () => { let r = 0, s = 0, b; do { b = buf[i++]; r |= (b & 0x7f) << s; s += 7; } while (b & 0x80); return r >>> 0; };
  const str = () => { const n = leb(); const t = new TextDecoder().decode(buf.subarray(i, i + n)); i += n; return t; };
  const imports: string[] = [], exports: string[] = [];
  while (i < buf.length) {
    const id = buf[i++], size = leb(), end = i + size;
    if (id === 2) {
      for (let n = leb(); n--;) {
        const m = str(), f = str(), k = buf[i++];
        imports.push(`${m}.${f}`);
        if (k === 0) leb(); else if (k === 1) { i++; const fl = leb(); leb(); if (fl & 1) leb(); }
        else if (k === 2) { const fl = leb(); leb(); if (fl & 1) leb(); } else if (k === 3) i += 2;
      }
    } else if (id === 7) {
      for (let n = leb(); n--;) { exports.push(str()); i++; leb(); }
    }
    i = end;
  }
  return { imports, exports };
}

// ---- OraclePet (BLE) ----
function petStatus(): any { try { return JSON.parse(readFileSync(STATUS, "utf8")); } catch { return {}; } }
function oraclePetRunning(): boolean {
  const pid = petStatus().pid;
  if (!pid) return false;
  try { process.kill(Number(pid), 0); return true; } catch { return false; }
}
async function ensureOraclePet(j: Job) {
  if (oraclePetRunning()) return;
  j.log.push("starting OraclePet…");
  Bun.spawnSync(["open", "-a", "OraclePet"]);
  for (let t = 0; t < 40; t++) { await Bun.sleep(500); if (oraclePetRunning()) return; }
  throw new Error("OraclePet is not running and did not start (is /Applications/OraclePet.app installed?)");
}
function findPet(suffix?: string): any {
  const pets: any[] = petStatus().pets ?? [];
  if (!suffix) return pets[0] ?? {};
  return pets.find((p) => String(p.name ?? "").toUpperCase().endsWith(suffix.toUpperCase())) ?? {};
}
const BUSY = /^(Starting|Sending|Pet is checking|Pet is restarting|Queued|Waiting)/;
/** The pet to use: the one asked for, else the first pet OraclePet has connected (never a pet
 * that is only "connecting": OraclePet would send to it and fail). */
function targetPet(pet: string | undefined): string {
  const pets: any[] = petStatus().pets ?? [];
  if (pet) {
    const p = pets.find((x) => String(x.name ?? "").toUpperCase().endsWith(pet.toUpperCase()));
    if (!p) throw new Error(`no pet named …${pet}; OraclePet knows ${pets.map((x) => x.name).join(", ") || "none"}`);
    if (p.link !== "connected") throw new Error(`${p.name} is ${p.link ?? "not linked"}, not connected`);
    return pet;
  }
  const p = pets.find((x) => x.link === "connected");
  if (!p) throw new Error(`no pet connected (OraclePet sees ${pets.map((x) => `${x.name}: ${x.link}`).join(", ") || "none"})`);
  return String(p.name).replace(/^Claude-/, "");
}

/** Ask OraclePet with a deskpet:// URL and follow pets[pet].ota until the transfer ends. */
async function deskpet(j: Job, host: string, q: Record<string, string | undefined>, petIn: string | undefined, timeoutS: number,
                       expect?: RegExp) {
  await ensureOraclePet(j);
  const pet = targetPet(petIn);
  j.log.push(`pet: Claude-${pet}`);
  q.pet = pet;
  const before = findPet(pet).ota ?? "";
  const qs = Object.entries(q).filter(([, v]) => v != null).map(([k, v]) => `${k}=${encodeURIComponent(v!)}`).join("&");
  const url = `deskpet://${host}?${qs}`;
  j.log.push(`→ ${url}`);
  Bun.spawnSync(["open", "-g", url]);
  const t0 = Date.now(), end = t0 + timeoutS * 1000;
  let seenBusy = false, last = before;
  while (Date.now() < end) {
    await Bun.sleep(300);
    const p = findPet(pet), ota = String(p.ota ?? "");
    if (ota !== last) { j.log.push(`${p.name ?? "pet"}: ${ota}`); last = ota; }
    const pct = ota.match(/(\d{1,3})%/);
    if (pct) j.progress = Number(pct[1]);
    const busy = BUSY.test(ota);
    if (busy) seenBusy = true;
    // the same request twice can leave the very same line ("Pet runs dice · 3813 bytes in 0 s"),
    // so after 3 s a line that already says the expected outcome counts too
    const same = !!expect && Date.now() - t0 > 3000 && expect.test(ota);
    if (ota && !busy && (seenBusy || ota !== before || same)) {
      if (/fail|refus|stall|lost|not a|cut short|is for the|no OTA service|flash it once|not linked|busy|no app/i.test(ota)) throw new Error(ota);
      j.progress = 100;
      return { pet: p.name, ota, firmware: p.firmware, pack: p.pack, app: p.app };
    }
  }
  throw new Error(`no answer from the pet within ${timeoutS} s (last: ${last || "nothing"})`);
}

// ---- the operations ----
function buildApp(body: any) {
  const name = String(body.name ?? "").toLowerCase();
  const ext = LANGS[String(body.lang ?? "c").toLowerCase()];
  if (!NAME.test(name)) throw new Error("name: lower-case a-z 0-9 - _, at most 23");
  if (!ext) throw new Error("lang: c, zig, rust or as");
  if (!body.source) throw new Error("source: the app's code");
  const src = join(WS, "apps", `${name}.${ext}`);
  writeFileSync(src, String(body.source));
  return job("app", `build app ${name} (${ext})`, "sdk", async (j) => {
    await sh(j, ["bash", "build.sh", src], { cwd: SDK });
    const wasm = join(SDK, "build", `${name}.wasm`);
    const bytes = new Uint8Array(readFileSync(wasm));
    const info = wasmInfo(bytes);
    const bad = (info?.imports ?? []).filter((x) => !x.startsWith("pet."));
    if (bad.length) throw new Error(`imports outside the pet API: ${bad.join(", ")}`);
    return { name, wasm, bytes: bytes.length, ...info, url: `/api/apps/${name}.wasm` };
  });
}

function createPack(body: any) {
  const name = String(body.name ?? "").toLowerCase();
  if (!NAME.test(name)) throw new Error("name: lower-case a-z 0-9 - _, at most 23");
  let image = body.imagePath ? String(body.imagePath) : "";
  if (body.imageBase64) {
    image = join(WS, "images", `${name}${body.imageExt ?? ".png"}`);
    writeFileSync(image, Buffer.from(String(body.imageBase64).replace(/^data:[^,]*,/, ""), "base64"));
  }
  const prompt = body.prompt ? String(body.prompt) : "";
  if (!image && !prompt) throw new Error("give imagePath, imageBase64 or prompt");
  return job("pack", `create pack ${name}`, "pack", async (j) => {
    if (!image) image = await imagegen(j, name, prompt);
    if (!existsSync(image)) throw new Error(`no image at ${image}`);
    await sh(j, ["bash", join(STUDIO, "tools/make-pack.sh"), name, image, join(WS, "packs")]);
    return packInfo(name);
  });
}

/** Codex image_gen (the /imagegen route): one character on a plain background, collected from ~/.codex. */
async function imagegen(j: Job, name: string, prompt: string): Promise<string> {
  const log = join(tmpdir(), `pet-studio-imagegen-${name}.log`);
  const ask = `Generate ONE image, square, no text, no logos: a single cute full-body character for a desk pet, front facing, ` +
    `standing, centred, on a plain flat white background, simple flat cartoon style with bold shapes that read at 96 px: ${prompt}. ` +
    `Reply with only the absolute path of the generated PNG.`;
  j.log.push("asking Codex image_gen (2-4 min)…");
  const p = Bun.spawn(["codex", "exec", "--skip-git-repo-check", "-C", tmpdir(), ask], { stdout: "pipe", stderr: "pipe" });
  const out = (await new Response(p.stdout).text()) + (await new Response(p.stderr).text());
  writeFileSync(log, out);
  await p.exited;
  const hits = out.match(/^\/Users\/[^ \n]+\/generated_images\/[^ \n]+\.png$/gm);
  const src = hits?.at(-1);
  if (!src || !existsSync(src)) throw new Error(`Codex gave no image (log: ${log})`);
  const dst = join(WS, "images", `${name}.png`);
  Bun.spawnSync(["magick", src, "-resize", "512x512", dst]);
  j.log.push(`image: ${dst}`);
  return dst;
}

/** Studio v2: a sprite pack from the designer's frames. `base` (the first idle frame) makes every
 * state through make-pack.sh's puppet moves; each state the designer drew frame by frame then
 * replaces its GIF with those frames (fitted to 96x100 on black, one 128-colour palette, whole
 * frames, no transparency: what the pet firmware plays). */
function createSprite(body: any) {
  const name = String(body.name ?? "").toLowerCase();
  if (!NAME.test(name)) throw new Error("name: lower-case a-z 0-9 - _, at most 23");
  const png = (d: string) => Buffer.from(String(d).replace(/^data:image\/png;base64,/, ""), "base64");
  if (!body.base) throw new Error("base: the first idle frame (PNG data URL)");
  const states: Record<string, string[]> = body.states ?? {};
  const known = ["idle", "busy", "attention", "celebrate", "dizzy", "sleep", "heart"];
  for (const k of Object.keys(states)) if (!known.includes(k)) throw new Error(`unknown state ${k}`);
  const dir = join(WS, "designs", name);
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, "base.png"), png(body.base));
  if (body.design) writeFileSync(join(dir, "design.json"), JSON.stringify(body.design));
  return job("sprite", `create sprite ${name}`, "pack", async (j) => {
    const files: Record<string, string[]> = {};
    for (const [state, frames] of Object.entries(states)) {
      if (!frames?.length) continue;
      files[state] = frames.map((f, i) => { const p = join(dir, `${state}-${String(i).padStart(2, "0")}.png`); writeFileSync(p, png(f)); return p; });
    }
    const drawn = await packFromFrames(j, name, join(dir, "base.png"), files, body.fps);
    j.log.push(drawn.length ? `drawn by hand: ${drawn.join(", ")}; the rest from the base frame` : "every state from the base frame");
    return { ...packInfo(name), drawn };
  });
}

/** A pack: make-pack.sh's puppet moves of `base` for every state, then each state in `files`
 * replaced by those frames (fitted to 96x100 on black, one 128-colour palette, whole frames, no
 * transparency: what the pet firmware plays). Returns "state (n frames)" for each replaced state. */
async function packFromFrames(j: Job, name: string, base: string, files: Record<string, string[]>, fps: any) {
  await sh(j, ["bash", join(STUDIO, "tools/make-pack.sh"), name, base, join(WS, "packs")]);
  const out = join(WS, "packs", name), drawn: string[] = [];
  for (const [state, list] of Object.entries(files)) {
    if (!list?.length) continue;
    const fitted = list.map((f) => f.replace(/\.png$/, "-96.png"));
    for (let i = 0; i < list.length; i++) {
      await sh(j, ["magick", list[i], "-background", "black", "-alpha", "remove", "-alpha", "off", "-filter", "Lanczos",
        "-resize", "96x100", "-gravity", "center", "-extent", "96x100", fitted[i]]);
    }
    const delay = String(Math.max(2, Math.round(100 / Math.max(1, Number(fps?.[state] ?? (typeof fps === "number" ? fps : 8))))));
    const gif = join(out, `${state}.gif`);
    await sh(j, ["magick", "-delay", delay, "-loop", "0", ...fitted, gif]);
    await sh(j, ["gifsicle", "--colors", "128", "-o", gif, gif]);
    await sh(j, ["gifsicle", "--unoptimize", "--no-transparent", "-o", gif, gif]);
    drawn.push(`${state} (${list.length} frames)`);
  }
  return drawn;
}

// ---- auto sprite: ONE picture in, every state redrawn by an image model (nexus-oracle#130) ----
// What AutoSprite (autosprite.io) does for game sheets, done the studio's way: Codex image_gen is
// shown the picture and draws the same character in new poses as one sheet (one image, so the
// character stays the same from pose to pose), tools/slice-sheet.py cuts it into frames, and then
// the AI checks its own work: Codex looks at the frames beside the picture and names the bad ones,
// which are drawn again state by state. No person in the loop; the result lands in workspace/
// designs/<name>/auto/, on the canvas (if one is named) and, with send, on the pet.
const MOVES: { state: string; poses: [string, string] }[] = [
  { state: "idle", poses: ["standing relaxed, eyes open, a small smile", "the same pose, eyes closed mid-blink"] },
  { state: "busy", poses: ["typing on a tiny laptop, hands on the keys", "typing, hands moved, looking at the screen"] },
  { state: "attention", poses: ["waving one arm high, mouth open saying hi", "the same wave, the arm lower"] },
  { state: "celebrate", poses: ["jumping, both arms up, very happy", "landing, a little squashed, arms out, happy"] },
  { state: "dizzy", poses: ["spiral eyes, wobbly, leaning left", "spiral eyes, wobbly, leaning right"] },
  { state: "sleep", poses: ["curled up lying down asleep, eyes closed", "the same sleeping pose breathing in, a little bigger"] },
  { state: "heart", poses: ["hugging a big red heart", "holding the red heart up high, eyes happy"] },
];
const SAME = "THIS SAME character as the attached picture: same colours, same proportions, same outfit and accessories, same face style";
const PLAIN = "every cell on the same plain flat pure white background, no grid lines, no borders, no text, no labels, no shadows on the ground";

/** codex exec with pictures attached; returns the PNG its image_gen wrote, or its last message. */
async function codexAsk(j: Job, tag: string, ask: string, images: string[], wantImage: boolean): Promise<string> {
  const dir = join(tmpdir(), "pet-studio-codex"); mkdirSync(dir, { recursive: true });
  const last = join(dir, `${tag}-last.txt`), log = join(dir, `${tag}.log`);
  // the prompt goes BEFORE -i: -i takes a list and would swallow it as one more picture
  const p = Bun.spawn(["codex", "exec", "--skip-git-repo-check", "-C", dir, "-o", last, ask, ...images.flatMap((i) => ["-i", i])], { stdout: "pipe", stderr: "pipe" });
  const out = (await new Response(p.stdout).text()) + (await new Response(p.stderr).text());
  writeFileSync(log, out);
  await p.exited;
  const msg = existsSync(last) ? readFileSync(last, "utf8").trim() : "";
  if (!wantImage) return msg;
  const hits = (msg + "\n" + out).match(/\/Users\/[^\s'"`]+\/generated_images\/[^\s'"`]+\.png/g);
  const src = hits?.reverse().find((h) => existsSync(h));
  if (!src) throw new Error(`Codex drew no picture for ${tag} (log: ${log})`);
  return src;
}

async function slice(j: Job, sheet: string, out: string, grid: string, cells: string[], fitTo?: string) {
  const p = Bun.spawn(["uv", "run", "-q", join(STUDIO, "tools/slice-sheet.py"), sheet, out, "--grid", grid, "--cells", cells.join(","),
    ...(fitTo && existsSync(fitTo) ? ["--fit-to", fitTo] : [])], { stdout: "pipe", stderr: "pipe" });
  const text = await new Response(p.stdout).text(), err = await new Response(p.stderr).text();
  if ((await p.exited) !== 0) throw new Error(`slice-sheet: ${err.trim().split("\n").at(-1)}`);
  j.log.push(`sliced ${basename(sheet)}: ${text.trim()}`);
  return JSON.parse(text.trim().split("\n").at(-1)!);
}

function autoSprite(body: any) {
  const name = String(body.name ?? "").toLowerCase();
  if (!NAME.test(name)) throw new Error("name: lower-case a-z 0-9 - _, at most 23");
  let image = body.imagePath ? String(body.imagePath) : body.image && NAME.test(String(body.image)) ? join(WS, "images", `${body.image}.png`) : "";
  if (body.imageBase64) {
    image = join(WS, "images", `${name}-ref.png`);
    writeFileSync(image, Buffer.from(String(body.imageBase64).replace(/^data:[^,]*,/, ""), "base64"));
  }
  const prompt = body.prompt ? String(body.prompt) : "";
  if (!image && !prompt) throw new Error("give image (a studio image name), imagePath, imageBase64 or prompt");
  if (image && !existsSync(image)) throw new Error(`no image at ${image}`);
  const custom: Record<string, string[]> = body.moves ?? {};
  for (const k of Object.keys(custom)) if (!MOVES.some((m) => m.state === k)) throw new Error(`moves: unknown state ${k}`);
  const moves = MOVES.map((m) => ({ state: m.state, poses: (custom[m.state]?.length ? [...custom[m.state], ...m.poses].slice(0, 2) : m.poses) as [string, string] }));
  const tries = Math.min(3, Math.max(0, Number(body.repairs ?? 2)));
  const dir = join(WS, "designs", name, "auto");
  return job("autosprite", `auto sprite ${name} from one picture`, `autosprite-${name}`, async (j) => {   // its own lane: several run at once
    rmSync(dir, { recursive: true, force: true }); mkdirSync(dir, { recursive: true });
    if (!image) { j.log.push("no picture given: drawing one first"); image = await imagegen(j, `${name}-ref`, prompt); }
    const ref = join(dir, "ref.png"); cpSync(image, ref);
    j.progress = 5;

    // 1. the sheet: 14 poses in one image, 4x4, reading order
    const cells = moves.flatMap((m) => [m.state, m.state]).concat(["-", "-"]);
    const list = moves.flatMap((m) => m.poses).map((p, i) => `${i + 1} ${moves[Math.floor(i / 2)].state}: ${p}`).join("; ");
    j.log.push("Codex image_gen draws the 14 poses as one sheet (2-5 min)…");
    const sheetSrc = await codexAsk(j, `${name}-sheet`, `Use your image generation tool. Generate ONE new square image: a sprite sheet of ${SAME}, ` +
      `full body, front facing, laid out as a strict 4x4 grid of equal square cells, ${PLAIN}. The character is centred in each cell, the same size in every cell, ` +
      `with a clear margin so no pose touches its cell's edge. Cells in reading order: ${list}; 15 empty; 16 empty. ` +
      `Reply with only the absolute path of the generated PNG.`, [ref], true);
    const sheet = join(dir, "sheet.png"); cpSync(sheetSrc, sheet);
    j.progress = 45;
    const frames = join(dir, "frames");
    await slice(j, sheet, frames, "4x4", cells);

    // 2. the AI checks its own work and redraws what is wrong, state by state, in parallel
    const reviews: any[] = [];
    for (let t = 0; t <= tries; t++) {
      const order = JSON.parse(readFileSync(join(frames, "sheet.json"), "utf8")).frames as string[];
      j.log.push(`review ${t + 1}: Codex compares the frames with the picture…`);
      const said = await codexAsk(j, `${name}-review${t}`, `First attached picture: a desk-pet character. Second: ${order.length} animation frames cut from an AI sprite sheet, ` +
        `left to right: ${order.map((f) => f.replace(/\.png$/, "")).join(", ")}. Each state has two frames that are MEANT to differ: ` +
        `${moves.map((m) => `${m.state}-1 = ${m.poses[0]}, ${m.state}-2 = ${m.poses[1]}`).join("; ")}. Flag a state ONLY for a real defect a viewer ` +
        `would notice at 96 px: a different character (colours, outfit, face), a pose that does not read as its description, a part cut off, ` +
        `two poses merged, or a frame missing. Small differences in style, expression or arm angle are fine. Answer with ONLY one JSON object, ` +
        `no prose: {"ok": true|false, "bad": ["state", ...], "notes": "one short line per bad state"}`,
        [ref, join(frames, "contact.png")], false);
      const m = said.match(/\{[\s\S]*\}/);
      let r: any = { ok: true, bad: [], notes: "review unreadable: kept as is" };
      try { if (m) r = JSON.parse(m[0]); } catch {}
      const bad = (Array.isArray(r.bad) ? r.bad : []).map(String).filter((s: string) => moves.some((x) => x.state === s));
      reviews.push({ round: t + 1, ok: !bad.length, bad, notes: r.notes ?? "" });
      j.log.push(bad.length ? `review ${t + 1}: redraw ${bad.join(", ")} (${r.notes ?? ""})` : `review ${t + 1}: every state passes`);
      if (!bad.length || t === tries) break;
      j.progress = 55 + t * 15;
      await Promise.all(bad.map(async (state: string) => {
        const mv = moves.find((x) => x.state === state)!;
        const src = await codexAsk(j, `${name}-${state}-r${t}`, `Use your image generation tool. Generate ONE new wide image, 2 equal square cells side by side: ${SAME} ` +
          `(the first attached picture; the second shows it in its idle pose at the same size), full body, front facing, ${PLAIN}, centred in each cell with a clear margin. ` +
          `Left cell: ${mv.poses[0]}. Right cell: ${mv.poses[1]}. ${r.notes ? `Fix what the last try got wrong: ${r.notes}.` : ""} Reply with only the absolute path of the generated PNG.`,
          [ref, join(frames, "idle-1.png")], true);
        const strip = join(dir, `${state}-strip-${t}.png`); cpSync(src, strip);
        const tmp = join(dir, `${state}-r${t}`);
        await slice(j, strip, tmp, "2x1", [state, state], join(frames, `${state}-1.png`));   // as tall as the frame it replaces
        for (const n of [1, 2]) if (existsSync(join(tmp, `${state}-${n}.png`))) cpSync(join(tmp, `${state}-${n}.png`), join(frames, `${state}-${n}.png`));
      }));
      // contact sheet again, from the frames as they are now
      await sh(j, ["magick", ...order.map((f) => join(frames, f)), "-background", "black", "-alpha", "remove", "-resize", "96x100", "+append", join(frames, "contact.png")]);
    }
    j.progress = 85;

    // 3. the pack, from the redrawn frames (make-pack.sh only for anything not drawn)
    const files: Record<string, string[]> = {};
    for (const m of moves) files[m.state] = [1, 2].map((n) => join(frames, `${m.state}-${n}.png`)).filter(existsSync);
    const fps = { idle: 2, busy: 4, attention: 3, celebrate: 3, dizzy: 3, sleep: 1, heart: 2, ...(body.fps ?? {}) };
    const drawn = await packFromFrames(j, name, files.idle[0] ?? ref, files, fps);
    cpSync(join(frames, "contact.png"), join(WS, "packs", name, "contact.png"));
    const urls = Object.fromEntries(Object.entries(files).map(([s, l]) => [s, l.map((f) => `/api/designs/${name}/auto/frames/${basename(f)}`)]));

    // 4. onto the canvas, one picture per frame, so a person (or agent) can touch it up after
    if (body.canvas) {
      const cvId = String(body.canvas), by = String(body.by ?? "auto sprite");
      try {
        for (const [s, l] of Object.entries(urls)) for (let i = 0; i < l.length; i++) {
          await callPage("goto", { state: s, frame: i + 1 }, 20000, cvId, by);
          await callPage("clear", {}, 20000, cvId, by);
          await callPage("image", { url: l[i], x: 0, y: 0, width: 384 }, 20000, cvId, by);
        }
        await callPage("goto", { state: "idle", frame: 1 }, 20000, cvId, by);
        j.log.push(`frames placed on canvas ${cvId}`);
      } catch (e: any) { j.log.push(`canvas ${cvId}: ${e?.message ?? e} (the pack is made anyway)`); }
    }
    let sent: string | undefined;
    if (body.send) {
      const b = flashBle({ kind: "pack", name, pet: body.pet });
      while (b.status === "queued" || b.status === "running") await Bun.sleep(500);
      sent = b.status === "ok" ? (b.log.filter((l) => /shows /.test(l)).at(-1) ?? "sent") : `not sent: ${b.error}`;
      j.log.push(`pet: ${sent}`);
    }
    j.progress = 100;
    return { ...packInfo(name), drawn, reviews, sheet: `/api/designs/${name}/auto/sheet.png`, contact: `/api/designs/${name}/auto/frames/contact.png`, frames: urls, sent };
  });
}

function generateImage(body: any) {
  const name = String(body.name ?? "").toLowerCase();
  if (!NAME.test(name)) throw new Error("name: lower-case a-z 0-9 - _, at most 23");
  if (!body.prompt) throw new Error("prompt: what to draw");
  return job("image", `generate image ${name}`, "pack", async (j) => {
    const p = await imagegen(j, name, String(body.prompt));
    // the designer wants it cut out: key the plain background like make-pack.sh does
    const cut = join(WS, "images", `${name}.png`);
    await sh(j, ["magick", p, "-alpha", "set", "-fuzz", "4%", "-fill", "none", "-draw", "alpha 0,0 floodfill",
      "-draw", "alpha %[fx:w-1],0 floodfill", "-trim", "+repage", cut]);
    return { name, url: `/api/images/${name}.png` };
  });
}

/** A web-flasher bundle: everything a Chrome tab needs to install the pet over USB (esp-web-tools),
 * with `pack` as the character a fresh pet boots with. Firmware built with PET_DEFAULT_PACK=pack;
 * storage.bin made like the firmware build makes it (littlefs-python, block 4096, name-max 64)
 * from the built-in packs plus every studio pack; offsets from the build's own flasher_args.json.
 * Output: workspace/flasher/<board>-<pack>/ (manifest.json, the .bin parts, index.html, a .zip),
 * served at /flasher/<board>-<pack>/. */
function stageFlasher(body: any) {
  const board = String(body.board ?? "");
  if (!BOARDS[board]) throw new Error(`board: ${Object.keys(BOARDS).join(", ")}`);
  const pack = String(body.pack ?? "").toLowerCase();
  if (!NAME.test(pack) || !packInfo(pack)) throw new Error(`no pack ${pack}`);
  // packs baked in: the boot pack plus any listed (default: just the boot pack), so the pet keeps
  // room for packs sent over BLE later (all 13 built-ins plus every studio pack overflow 3 MB)
  const packs: string[] = [...new Set([pack, ...(Array.isArray(body.packs) ? body.packs.map(String) : [])])];
  for (const p of packs) if (!NAME.test(p) || !packInfo(p)) throw new Error(`no pack ${p}`);
  // apps baked into storage (apps/<name>.wasm); `autorun` (one of them) starts on the first boot
  const apps: string[] = (Array.isArray(body.apps) ? body.apps : []).map(String);
  const autorun = body.autorun ? String(body.autorun) : apps.length === 1 ? apps[0] : "";
  for (const a of apps) if (!NAME.test(a) || !existsSync(join(SDK, "build", `${a}.wasm`))) throw new Error(`no built app ${a} (pet-sdk/build/${a}.wasm)`);
  if (autorun && !apps.includes(autorun)) throw new Error(`autorun ${autorun} is not one of apps`);
  const b = BOARDS[board], bdir = join(FW, b.dir), id = `${board}-${pack}`, out = join(WS, "flasher", id);
  return job("flasher", `web flasher ${id}${packs.length > 1 ? ` (+${packs.length - 1} packs)` : ""}${apps.length ? ` + ${apps.join(", ")}` : ""}`, "idf", async (j) => {
    await idf(j, `idf.py -B ${b.dir} ${b.defs} -DPET_DEFAULT_PACK=${pack} build`);
    rmSync(out, { recursive: true, force: true });
    mkdirSync(out, { recursive: true });
    // storage: the firmware's data/ without its characters, plus just the chosen packs
    const stage = join(tmpdir(), `pet-flasher-${id}`);
    rmSync(stage, { recursive: true, force: true });
    cpSync(join(FW, "data"), stage, { recursive: true, filter: (src) => !src.includes("/characters/") });
    mkdirSync(join(stage, "characters"), { recursive: true });
    for (const p of packs) cpSync(packInfo(p)!.dir, join(stage, "characters", p), { recursive: true });
    j.log.push(`packs baked in: ${packs.join(", ")}`);
    if (apps.length) {
      mkdirSync(join(stage, "apps"), { recursive: true });
      for (const a of apps) cpSync(join(SDK, "build", `${a}.wasm`), join(stage, "apps", `${a}.wasm`));
      if (autorun) writeFileSync(join(stage, "apps", "autorun"), autorun + "\n");
      j.log.push(`apps baked in: ${apps.join(", ")}${autorun ? `; ${autorun} starts on the first boot` : ""}`);
    }
    const args = JSON.parse(readFileSync(join(bdir, "flasher_args.json"), "utf8"));
    const files: Record<string, string> = args.flash_files;
    const storageOff = Object.entries(files).find(([, f]) => f === "storage.bin")?.[0];
    if (!storageOff) throw new Error("the build has no storage.bin part");
    const py = join(bdir, "littlefs_py_venv", "bin", "python");
    const parts = readFileSync(join(FW, "partitions.csv"), "utf8").split("\n").find((l) => l.startsWith("storage"))!;
    const fsSize = parts.split(",").map((x) => x.trim())[4];
    const used = Number(Bun.spawnSync(["du", "-sk", stage]).stdout.toString().split(/\s/)[0]) * 1024;
    const cap = parseInt(fsSize, 16) || Number(fsSize);
    if (used > cap * 0.9) throw new Error(`too much for the ${(cap / 1048576).toFixed(1)} MB storage: ${(used / 1048576).toFixed(2)} MB; bake fewer packs`);
    j.log.push(`storage: ${(used / 1024).toFixed(0)} KB of ${(cap / 1024).toFixed(0)} KB, ${((cap - used) / 1024).toFixed(0)} KB left for packs sent over BLE`);
    await sh(j, [py, "-m", "littlefs", "create", stage, join(out, "storage.bin"), "-v", `--fs-size=${fsSize}`, "--name-max=64", "--block-size=4096"]);
    const manifestParts: { path: string; offset: number }[] = [];
    for (const [off, f] of Object.entries(files)) {
      const name = basename(f);
      if (name !== "storage.bin") cpSync(join(bdir, f), join(out, name));
      manifestParts.push({ path: name, offset: parseInt(off, 16) });
    }
    manifestParts.sort((a, b2) => a.offset - b2.offset);
    const chip = String(args.extra_esptool_args?.chip ?? "esp32s3").toUpperCase().replace("ESP32S3", "ESP32-S3");
    writeFileSync(join(out, "manifest.json"), JSON.stringify({
      name: `OraclePet ${b.label}: ${pack}`, version: new Date().toISOString().slice(0, 10), new_install_prompt_erase: false,
      builds: [{ chipFamily: chip, parts: manifestParts }],
    }, null, 2));
    cpSync(join(WS, "packs", pack), join(out, "pack"), { recursive: true });
    writeFileSync(join(out, "index.html"), flasherPage(b.label, pack, apps, autorun));
    await sh(j, ["zip", "-qr", `${out}.zip`, "."], { cwd: out } as any);
    rmSync(stage, { recursive: true, force: true });
    return { board, pack, packs, apps, autorun: autorun || null, storageKB: Math.round(used / 1024), freeKB: Math.round((cap - used) / 1024), dir: out, url: `/flasher/${id}/`, zip: `/flasher/${id}.zip`, parts: manifestParts };
  });
}

function flasherPage(label: string, pack: string, apps: string[] = [], autorun = "") {
  const states = ["idle", "busy", "attention", "celebrate", "dizzy", "sleep", "heart"];
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Install ${pack} on the ${label}</title>
<script type="module" src="https://unpkg.com/esp-web-tools@9.4.3/dist/web/install-button.js?module"></script>
<style>body{margin:0;font:15px/1.5 system-ui,sans-serif;background:#e7ebf0;color:#16181d}main{max-width:720px;margin:40px auto;padding:28px;background:#fff;border-radius:16px;box-shadow:0 0 0 3px #fff,0 10px 24px -12px rgba(0,0,0,.25)}
h1{margin:0 0 4px;font-size:24px}p{margin:0 0 18px;color:#4a5160}.g{display:grid;grid-template-columns:repeat(7,1fr);gap:8px;margin:18px 0 24px}
figure{margin:0;text-align:center;font-size:12px;color:#6b7383}img{width:100%;aspect-ratio:96/100;background:#16181d;border-radius:8px;image-rendering:pixelated}
esp-web-install-button button{font:inherit}</style></head><body><main>
<h1>${pack}, on the ${label}</h1>
<p>Plug the pet in by USB, then install from Chrome or Edge. This writes the pet firmware and every character pack; the pet boots as <b>${pack}</b>.${apps.length ? ` Apps on board: <b>${apps.join(", ")}</b>${autorun ? `; <b>${autorun}</b> starts by itself on the first boot` : ""}.` : ""}</p>
<div class="g">${states.map((s) => `<figure><img src="pack/${s}.gif" alt="${s}"><figcaption>${s}</figcaption></figure>`).join("")}</div>
<esp-web-install-button manifest="manifest.json"></esp-web-install-button>
<p style="margin-top:18px;font-size:13px">Made with Pet Studio. Needs a Chromium browser (Web Serial) on https or localhost.</p>
</main></body></html>`;
}

function packInfo(name: string) {
  for (const root of [join(WS, "packs"), join(FW, "data/characters")]) {
    const dir = join(root, name);
    if (!existsSync(join(dir, "manifest.json"))) continue;
    const files = readdirSync(dir).filter((f) => f.endsWith(".gif") || f === "manifest.json")
      .map((f) => ({ name: f, bytes: statSync(join(dir, f)).size, url: `/api/packs/${name}/${f}` }));
    return { name, dir, builtIn: root !== join(WS, "packs"), bytes: files.reduce((a, f) => a + f.bytes, 0), files };
  }
  return null;
}

function buildFirmware(body: any) {
  const board = String(body.board ?? "");
  if (!BOARDS[board]) throw new Error(`board: ${Object.keys(BOARDS).join(", ")}`);
  const pack = body.pack ? String(body.pack) : "siamese";
  if (!NAME.test(pack)) throw new Error("pack: a pack name");
  const b = BOARDS[board];
  return job("firmware", `build firmware ${board}`, "idf", async (j) => {
    await idf(j, `idf.py -B ${b.dir} ${b.defs} -DPET_DEFAULT_PACK=${pack} build`);
    const bin = firmwareBin(board);
    return { board, bin, bytes: statSync(bin).size, built: statSync(bin).mtime };
  });
}

function flashBle(body: any) {
  const kind = String(body.kind ?? "");
  const pet = targetPet(body.pet ? String(body.pet) : undefined);   // fail now, not after a 60 s wait
  if (kind === "firmware") {
    const board = String(body.board ?? "");
    if (!BOARDS[board]) throw new Error(`board: ${Object.keys(BOARDS).join(", ")}`);
    const bin = firmwareBin(board);
    if (!existsSync(bin)) throw new Error(`no ${board} firmware built yet (${bin})`);
    return job("ble", `BLE firmware ${board} -> ${pet ?? "pet"}`, "ble", (j) => deskpet(j, "ota", { file: bin }, pet, 240));
  }
  if (kind === "app") {
    const name = String(body.name ?? "");
    const wasm = join(SDK, "build", `${name}.wasm`);
    if (!NAME.test(name) || !existsSync(wasm)) throw new Error(`no app ${name} built (${wasm})`);
    return job("ble", `BLE app ${name} -> ${pet ?? "pet"}`, "ble", (j) => deskpet(j, "app", { file: wasm }, pet, 60, new RegExp(`runs ${name}\\b`)));
  }
  if (kind === "run") {
    const name = String(body.name ?? "");
    return job("ble", `run app ${name} on ${pet ?? "pet"}`, "ble", (j) => deskpet(j, "app", { run: name }, pet, 20, name === "stop" ? /stopped/i : new RegExp(`runs ${name}\\b`)));
  }
  if (kind === "pack") {
    const info = packInfo(String(body.name ?? ""));
    if (!info) throw new Error(`no pack ${body.name}`);
    const q = info.builtIn ? { name: info.name } : { dir: info.dir };
    return job("ble", `BLE pack ${info.name} -> ${pet ?? "pet"}`, "ble", (j) => deskpet(j, "pack", q, pet, 180, new RegExp(`shows ${info.name}\\b`)));
  }
  throw new Error("kind: firmware, app, run or pack");
}

function flashUsb(body: any) {
  const board = String(body.board ?? ""), port = String(body.port ?? "");
  if (!BOARDS[board]) throw new Error(`board: ${Object.keys(BOARDS).join(", ")}`);
  if (!/^\/dev\/cu\.[A-Za-z0-9._-]+$/.test(port)) throw new Error("port: /dev/cu.usbmodem…");
  const b = BOARDS[board];
  return job("usb", `USB flash ${board} -> ${port}`, "idf", (j) =>
    idf(j, `idf.py -B ${b.dir} ${b.defs} -p ${port} flash`).then(() => ({ board, port })));
}

function state() {
  const s = petStatus();
  const ports = (() => { try { return readdirSync("/dev").filter((d) => d.startsWith("cu.usbmodem")).map((d) => `/dev/${d}`); } catch { return []; } })();
  const apps = existsSync(join(SDK, "build")) ? readdirSync(join(SDK, "build")).filter((f) => f.endsWith(".wasm"))
    .map((f) => ({ name: f.slice(0, -5), bytes: statSync(join(SDK, "build", f)).size, url: `/api/apps/${f}` })) : [];
  const packs = [join(WS, "packs"), join(FW, "data/characters")].flatMap((r) => existsSync(r) ? readdirSync(r) : [])
    .filter((n, i, a) => a.indexOf(n) === i).map(packInfo).filter(Boolean);
  const firmware = Object.entries(BOARDS).map(([id, b]) => {
    const bin = firmwareBin(id);
    return { board: id, label: b.label, project: b.project, bin, built: existsSync(bin) ? statSync(bin).mtime : null,
             bytes: existsSync(bin) ? statSync(bin).size : 0 };
  });
  const sources = existsSync(join(WS, "apps")) ? readdirSync(join(WS, "apps")) : [];
  return {
    oraclePet: { running: oraclePetRunning(), at: s.at },
    pets: (s.pets ?? []).map((p: any) => ({ name: p.name, link: p.link, firmware: p.firmware, pack: p.pack, app: p.app, ota: p.ota })),
    ports, boards: BOARDS, firmware, apps, packs, sources,
    jobs: [...jobs.values()].reverse().slice(0, 30).map(({ log, ...rest }) => ({ ...rest, last: log.at(-1) })),
  };
}

// ---- HTTP ----
const json = (d: any, status = 200) => new Response(JSON.stringify(d, null, 2), { status, headers: { "content-type": "application/json" } });
const TYPES: Record<string, string> = { ".zip": "application/zip", ".bin": "application/octet-stream", ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml",
  ".wasm": "application/wasm", ".gif": "image/gif", ".png": "image/png", ".json": "application/json" };
const file = (p: string) => new Response(Bun.file(p), { headers: { "content-type": TYPES[extname(p)] ?? "application/octet-stream" } });

const server = Bun.serve<WsData>({
  hostname: "127.0.0.1",
  port: PORT,
  idleTimeout: 120,
  websocket: {
    open(ws) { wsSubs.add(ws); ws.send(JSON.stringify({ type: "hello", ...liveSummary() })); },
    close(ws) { wsSubs.delete(ws); dropOrigin(ws.data.origin); },
    message() {},
    idleTimeout: 0,
    sendPings: true,
  },
  async fetch(req, srv) {
    const u = new URL(req.url), path = u.pathname;
    if (path === "/api/live/ws") {
      return srv.upgrade(req, { data: { origin: u.searchParams.get("origin") ?? "" } }) ? undefined : json({ error: "websocket upgrade failed" }, 400);
    }
    try {
      if (path === "/api/health") return json({ ok: true });
      if (path === "/api/state") return json(state());
      if (path === "/api/jobs") return json([...jobs.values()].reverse().map(({ log, ...r }) => r));
      let m = path.match(/^\/api\/jobs\/([\w-]+)$/);
      if (m) { const j = jobs.get(m[1]); return j ? json(j) : json({ error: "no such job" }, 404); }
      m = path.match(/^\/api\/apps\/([a-z0-9_-]{1,23})\.wasm$/);
      if (m) { const p = join(SDK, "build", `${m[1]}.wasm`); return existsSync(p) ? file(p) : json({ error: "no such app" }, 404); }
      m = path.match(/^\/api\/apps\/([a-z0-9_-]{1,23})\/source$/);
      if (m) {
        const hit = [...(existsSync(join(WS, "apps")) ? readdirSync(join(WS, "apps")).map((f) => join(WS, "apps", f)) : []),
          ...readdirSync(join(SDK, "examples")).map((f) => join(SDK, "examples", f))].find((p) => basename(p).replace(/\.[^.]+$/, "") === m![1]);
        return hit ? json({ name: m[1], lang: extname(hit).slice(1), source: readFileSync(hit, "utf8") }) : json({ error: "no source" }, 404);
      }
      m = path.match(/^\/api\/designs\/([a-z0-9_-]{1,23})\/auto\/((?:frames\/)?[a-z0-9_.-]+\.png)$/);
      if (m) { const p = join(WS, "designs", m[1], "auto", m[2]); return existsSync(p) ? new Response(Bun.file(p), { headers: { "content-type": "image/png", "cache-control": "no-store" } }) : json({ error: "no such file" }, 404); }
      m = path.match(/^\/api\/images\/([a-z0-9_-]{1,23})\.png$/);
      if (m) { const p = join(WS, "images", `${m[1]}.png`); return existsSync(p) ? file(p) : json({ error: "no such image" }, 404); }
      m = path.match(/^\/flasher\/([a-z0-9_-]+)(\.zip|\/.*)?$/);
      if (m) {
        if (m[2] === ".zip") { const z = join(WS, "flasher", `${m[1]}.zip`); return existsSync(z) ? file(z) : json({ error: "no such bundle" }, 404); }
        const rel = (m[2] ?? "/").slice(1) || "index.html";
        if (rel.includes("..")) return json({ error: "bad path" }, 400);
        const f = join(WS, "flasher", m[1], rel);
        return existsSync(f) && statSync(f).isFile() ? file(f) : json({ error: "no such file" }, 404);
      }
      if (path === "/v2" || path === "/v2/") return existsSync(join(DIST, "v2.html")) ? file(join(DIST, "v2.html")) : json({ error: "build the page: bun run build" }, 404);
      m = path.match(/^\/api\/packs\/([a-z0-9_-]{1,23})\/([a-z0-9_.-]+)$/);
      if (m) { const info = packInfo(m[1]); const p = info && join(info.dir, m[2]); return p && existsSync(p) ? file(p) : json({ error: "no such file" }, 404); }
      if (path === "/api/live") return json(liveSummary());
      if (path === "/api/live/screen.png") {
        return live.screen ? new Response(live.screen.png as unknown as BodyInit, { headers: { "content-type": "image/png", "cache-control": "no-store" } })
          : json({ error: "no screen yet: open the page and run an app in the simulator" }, 404);
      }
      if (path === "/api/live/events") {
        let me: ReadableStreamDefaultController<Uint8Array>;
        const origin = u.searchParams.get("origin") ?? "";
        // a closed page leaves the routing table, so a call reopens its canvas instead of timing out
        const gone = () => { for (const [cv, d] of designers) if (d.origin === origin) designers.delete(cv); };
        const stream = new ReadableStream<Uint8Array>({
          start(c) { me = c; subs.add(c); c.enqueue(new TextEncoder().encode(`data: ${JSON.stringify({ type: "hello", ...liveSummary() })}\n\n`)); },
          cancel() { subs.delete(me); gone(); },
        });
        const ping = setInterval(() => { try { me.enqueue(new TextEncoder().encode(": ping\n\n")); } catch { clearInterval(ping); subs.delete(me); } }, 15000);
        req.signal.addEventListener("abort", () => { clearInterval(ping); subs.delete(me); gone(); });
        return new Response(stream, { headers: { "content-type": "text/event-stream", "cache-control": "no-store", connection: "keep-alive" } });
      }
      if (path === "/api/canvases") {
        const saved = existsSync(join(WS, "canvases")) ? readdirSync(join(WS, "canvases")).filter((f) => f.endsWith(".json")).map((f) => f.slice(0, -5)) : [];
        return json({ open: [...designers.keys()], saved, url: `http://127.0.0.1:${PORT}/v2?canvas=<id>` });
      }
      m = path.match(/^\/api\/canvas\/([a-z0-9_-]{1,32})\/(log|since)$/);
      if (m) {
        const lf = join(WS, "canvases", `${m[1]}.log.jsonl`);
        if (m[2] === "log" && req.method === "POST") {
          const b = await req.json();
          const rows = existsSync(lf) ? readFileSync(lf, "utf8").trim().split("\n").filter(Boolean).length : 0;
          const row = { seq: rows + 1, at: String(b.at ?? new Date().toISOString()), by: String(b.by ?? "person").slice(0, 24), what: String(b.what ?? "").slice(0, 200) };
          mkdirSync(join(WS, "canvases"), { recursive: true });
          appendFileSync(lf, JSON.stringify(row) + "\n");
          return json({ seq: row.seq });
        }
        const all = existsSync(lf) ? readFileSync(lf, "utf8").trim().split("\n").filter(Boolean).map((l) => JSON.parse(l)) : [];
        const cursor = Number(u.searchParams.get("cursor") ?? 0), limit = Number(u.searchParams.get("limit") ?? 100);
        const rows = all.filter((r: any) => r.seq > cursor);
        return json({ canvas: m[1], cursor: all.length, changes: rows.slice(-limit), skipped: Math.max(0, rows.length - limit) });
      }
      m = path.match(/^\/api\/canvas\/([a-z0-9_-]{1,32})$/);
      if (m && req.method === "GET") {
        const f = join(WS, "canvases", `${m[1]}.json`);
        return existsSync(f) ? new Response(Bun.file(f), { headers: { "content-type": "application/json" } }) : json({ error: "no such canvas" }, 404);
      }
      if (m && req.method === "POST") {
        mkdirSync(join(WS, "canvases"), { recursive: true });
        await Bun.write(join(WS, "canvases", `${m[1]}.json`), await req.text());
        return json({ saved: m[1] });
      }
      if (path === "/api/blocks/types") return json({ supported: SUPPORTED });
      if (req.method === "POST") {
        const body = await req.json().catch(() => ({}));
        if (path === "/api/live/blocks") {
          const c = blocksToC(body.blocks, String(body.name ?? live.name));   // throws (400) on blocks it cannot read
          Object.assign(live, { blocks: body.blocks, c, name: String(body.name ?? live.name), rev: live.rev + 1 });
          push({ type: "blocks", origin: body.origin ?? "agent", name: live.name, blocks: live.blocks, c, rev: live.rev });
          return json({ rev: live.rev, c });
        }
        if (path === "/api/live/code") {
          live.code = { name: String(body.name ?? "studio-hello"), lang: String(body.lang ?? "c"), source: String(body.source ?? "") };
          live.rev++;
          push({ type: "code", origin: body.origin ?? "agent", ...live.code, rev: live.rev });
          return json({ rev: live.rev });
        }
        if (path === "/api/live/sim") { live.sim = body.view ?? null; return json({ ok: true }); }
        if (path === "/api/live/screen") {
          const b64 = String(body.png ?? "").replace(/^data:image\/png;base64,/, "");
          live.screen = { png: new Uint8Array(Buffer.from(b64, "base64")), at: Date.now() };
          return json({ ok: true });
        }
        if (path === "/api/live/hello") {
          const cv = String(body.canvas ?? "main");
          if (body.role === "designer" && CANVAS.test(cv)) designers.set(cv, { origin: String(body.origin), at: Date.now() });
          return json({ ok: true });
        }
        if (path === "/api/live/result") {
          const f = pending.get(String(body.id));
          if (f) { pending.delete(String(body.id)); f({ ok: !!body.ok, result: body.result, error: body.error }); }
          return json({ ok: true });
        }
        if (path === "/api/live/call") {
          let args = body.args ?? {};
          // a file on this Mac becomes a data URL the page can load
          if (args.path && !args.url) {
            const p = String(args.path);
            if (!existsSync(p)) throw new Error(`no file ${p}`);
            const ext = extname(p).slice(1).toLowerCase().replace("jpg", "jpeg");
            const mime = ext === "svg" ? "image/svg+xml" : `image/${ext}`;
            args = { ...args, url: `data:${mime};base64,${readFileSync(p).toString("base64")}` };
            delete args.path;
          }
          const cv = String(body.canvas ?? "main"), by = String(body.by ?? "agent").slice(0, 24);
          if (!CANVAS.test(cv)) throw new Error("canvas: a-z 0-9 - _, at most 32");
          return json({ result: await callPage(String(body.action), args, Number(body.timeoutMs ?? 20000), cv, by) });
        }
        if (path === "/api/live/command") {
          if (!pageCount()) return json({ error: "no page open: open http://127.0.0.1:" + PORT }, 409);
          push({ ...body, origin: "agent" });
          return json({ sent: body.type, pages: pageCount() });
        }
        if (path === "/api/blocks/build") {
          if (body.blocks) {
            const c = blocksToC(body.blocks, String(body.name ?? live.name));
            Object.assign(live, { blocks: body.blocks, c, rev: live.rev + 1 });
            push({ type: "blocks", origin: body.origin ?? "agent", name: live.name, blocks: live.blocks, c, rev: live.rev });
          }
          const name = String(body.name ?? live.name);
          // an empty workspace (no event block with anything in it) must not replace a working app:
          // that is how dice.wasm became an empty on_start (a stale page pushed an empty sheet)
          const tops: any[] = (live.blocks as any)?.blocks?.blocks ?? [];
          if (!tops.some((t) => String(t.type).startsWith("pet_on_") || t.type === "pet_every" ? t.inputs?.DO : false)) {
            throw new Error(`nothing to build: the blocks have no event block with blocks inside (${name}.wasm left as it is)`);
          }
          live.name = name;
          const j = buildApp({ name, lang: "c", source: blocksToC(live.blocks, name) });
          const watch = setInterval(() => {
            if (j.status === "ok") { clearInterval(watch); push({ type: "built", origin: "server", name, simulate: body.simulate !== false }); }
            if (j.status === "failed") clearInterval(watch);
          }, 200);
          return json({ job: j.id, title: j.title });
        }
        const ops: Record<string, (b: any) => Job> = {
          "/api/apps/build": buildApp, "/api/packs/create": createPack, "/api/firmware/build": buildFirmware,
          "/api/flash/ble": flashBle, "/api/flash/usb": flashUsb, "/api/sprite/create": createSprite, "/api/images/generate": generateImage, "/api/flasher/stage": stageFlasher, "/api/sprite/auto": autoSprite,
        };
        if (ops[path]) { const j = ops[path](body); return json({ job: j.id, title: j.title }); }
      }
      if (!path.startsWith("/api/") && existsSync(DIST)) {
        // relic5: the designer canvas is the only page, at / and /v2 (and any page path falls back to it)
        const p = join(DIST, path === "/" ? "v2.html" : path.slice(1));
        return existsSync(p) && statSync(p).isFile() ? file(p) : file(join(DIST, "v2.html"));
      }
      return json({ error: `no route ${req.method} ${path}` }, 404);
    } catch (e: any) {
      return json({ error: String(e?.message ?? e) }, 400);
    }
  },
});
console.log(`pet-studio on http://${server.hostname}:${server.port}  (lab: ${LAB})`);
