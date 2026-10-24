import { useEffect, useRef, useState } from "react";
import { api, type Job, type Pack, type State } from "./api";
import { BlocksTab } from "./BlocksTab";
import { onLive, ORIGIN, sendCode, startLive, useLiveConnected } from "./live";
import { SimScreen } from "./SimScreen";
import { setPacks, simulate, setPack } from "./simstore";

const STARTER: Record<string, string> = {
  c: `#include "pet.h"

static int taps;

PET_EXPORT("on_start") void on_start(void)
{
    pet_caption("hello from studio");
    pet_status("app: studio");
}

PET_EXPORT("on_tap") void on_tap(int x, int y)
{
    char b[24]; int at = 0;
    taps++;
    pet_put_str(b, &at, "taps: ");
    pet_put_int(b, &at, taps);
    pet_caption(b);
    pet_sound(PET_BLIP_UP);
    if (taps % 3 == 0) pet_react();
}
`,
  zig: `const pet = @import("pet");

export fn on_start() void {
    pet.caption("hello from zig");
}
`,
  rust: `#![no_std]
#[path = "../../pet-sdk/rust/pet.rs"] mod pet;

#[no_mangle]
pub extern "C" fn on_start() { pet::caption("hello from rust"); }

#[panic_handler]
fn panic(_: &core::panic::PanicInfo) -> ! { loop {} }
`,
  as: `import { caption } from "../../pet-sdk/assemblyscript/pet";

export function on_start(): void { caption("hello from AS"); }
`,
};

const TABS = ["Blocks", "Code", "Image", "Firmware", "Jobs"] as const;
type Tab = (typeof TABS)[number];

function useJob(onDone?: (j: Job) => void) {
  const [job, setJob] = useState<Job | null>(null);
  const [id, setId] = useState<string | null>(null);
  const done = useRef(onDone);
  done.current = onDone;
  useEffect(() => {
    if (!id) return;
    let stop = false;
    const tick = async () => {
      const j = await api.job(id).catch(() => null);
      if (stop || !j) return;
      setJob(j);
      if (j.status === "ok" || j.status === "failed") { done.current?.(j); return; }
      setTimeout(tick, 700);
    };
    tick();
    return () => { stop = true; };
  }, [id]);
  return { job, start: (jobId: string) => { setJob(null); setId(jobId); } };
}

function JobLog({ job }: { job: Job | null }) {
  const ref = useRef<HTMLPreElement>(null);
  useEffect(() => { ref.current?.scrollTo(0, ref.current.scrollHeight); }, [job?.log?.length]);
  if (!job) return null;
  const bar = job.status === "ok" ? 100 : job.progress;
  return (
    <div className="mt-2.5 space-y-1.5">
      <div className="flex flex-wrap items-center gap-2">
        <b>{job.title}</b> <span className={`pill ${job.status}`}>{job.status}</span>
        {job.ended && <span className="text-dim">{((job.ended - job.started) / 1000).toFixed(1)} s</span>}
        {job.status === "queued" && <span className="text-accent">waiting for: {job.waitingFor ?? "the job ahead"}</span>}
        {job.status === "failed" && <span className="text-bad">{job.error}</span>}
      </div>
      {bar !== undefined && (
        <div className="h-2 w-full overflow-hidden rounded-full bg-line">
          <div className={`h-full rounded-full transition-all duration-300 ${job.status === "failed" ? "bg-bad" : job.status === "ok" ? "bg-ok" : "bg-accent"}`} style={{ width: `${bar}%` }} />
        </div>
      )}
      {job.status === "running" && bar === undefined && (
        <div className="h-2 w-full overflow-hidden rounded-full bg-line"><div className="h-full w-1/3 animate-pulse rounded-full bg-accent" /></div>
      )}
      <pre ref={ref}>{(job.log ?? []).slice(-400).join("\n")}</pre>
    </div>
  );
}

function Dot({ on, title }: { on: boolean; title: string }) {
  return <span title={title} className={`inline-block size-2.5 rounded-full ${on ? "bg-ok" : "bg-bad"}`} />;
}

export default function App() {
  const [tab, setTab] = useState<Tab>("Blocks");
  const live = useLiveConnected();
  const blocksJob = useJob(() => refresh());
  useEffect(() => { startLive(); }, []);
  useEffect(() => onLive((e) => {
    if (e.type === "blocks") setTab("Blocks");
    if (e.type === "code") setTab("Code");
    if (e.type === "tab" && TABS.includes(e.tab)) setTab(e.tab);
  }), []);
  const [st, setSt] = useState<State | null>(null);
  const [pet, setPet] = useState<string>("");
  const [err, setErr] = useState("");
  const refresh = () => api.state().then((s) => { setSt(s); setPacks(s.packs.map((p) => p.name)); }).catch((e) => setErr(String(e)));
  useEffect(() => { refresh(); const t = setInterval(refresh, 2000); return () => clearInterval(t); }, []);
  const guard = async (f: () => Promise<void>) => { setErr(""); try { await f(); } catch (e: any) { setErr(e.message ?? String(e)); } };
  const suffix = (name: string) => name.replace(/^Claude-/, "");
  const autoPet = st?.pets.find((p) => p.link === "connected")?.name;

  return (
    <div className="min-h-screen">
      <header className="flex flex-wrap items-center gap-x-6 gap-y-2.5 border-b border-line px-5 py-3">
        <h1>🐾 Pet Studio</h1>
        <div className="flex flex-1 flex-wrap items-center gap-2">
          <Dot on={!!st?.oraclePet.running} title="OraclePet carries every BLE transfer" />
          <span>OraclePet {st?.oraclePet.running ? "running" : "not running"}</span>
          {st?.pets.map((p) => (
            <button key={p.name} disabled={p.link !== "connected"} className={`chip ${pet === suffix(p.name) ? "sel" : ""}`}
              onClick={() => setPet(pet === suffix(p.name) ? "" : suffix(p.name))} title={`${p.firmware ?? ""}\n${p.ota ?? ""}`}>
              <span className={p.link === "connected" ? "text-ok" : "text-dim"}>●</span> {p.name} · {p.link ?? "?"}{p.pack ? ` · ${p.pack}` : ""}{p.app ? ` · app ${p.app}` : ""}
            </button>
          ))}
          {st && !st.pets.length && <span className="text-dim">no pet linked</span>}
          <span className="text-dim">USB: {st?.ports.join(", ") || "none"}</span>
          <Dot on={live} title="live link: the agent's MCP tools see and edit this page" /><span>live</span>
        </div>
        <nav className="flex gap-1">{TABS.map((t) => <button key={t} className={tab === t ? "sel" : ""} onClick={() => setTab(t)}>{t}</button>)}</nav>
      </header>
      {err && <div className="mx-5 mt-2.5 cursor-pointer rounded-lg border border-bad bg-[#3a1414] px-3 py-2" onClick={() => setErr("")}>{err}</div>}
      <main className="px-5 py-4">
        {tab === "Blocks" && st && <BlocksTab st={st} pet={pet} guard={guard} refresh={refresh} start={blocksJob.start} jobLog={<JobLog job={blocksJob.job} />} />}
        {tab === "Code" && st && <AppTab st={st} pet={pet} guard={guard} refresh={refresh} />}
        {tab === "Image" && st && <ImageTab st={st} pet={pet} guard={guard} refresh={refresh} />}
        {tab === "Firmware" && st && <FirmwareTab st={st} pet={pet} guard={guard} refresh={refresh} />}
        {tab === "Jobs" && st && <JobsTab st={st} />}
      </main>
      <footer className="px-5 pb-5 text-xs text-dim">Target pet: <b className="text-[#e6e6e6]">{pet ? `Claude-${pet}` : autoPet ? `auto: ${autoPet}` : "none connected"}</b> · AI-built by Nexus (Claude) for Nat · Rule 6</footer>
    </div>
  );
}

type TabProps = { st: State; pet: string; guard: (f: () => Promise<void>) => Promise<void>; refresh: () => void };

function AppTab({ st, pet, guard, refresh }: TabProps) {
  const [name, setName] = useState("studio-hello");
  const [lang, setLang] = useState("c");
  const [src, setSrc] = useState(STARTER.c);
  const [built, setBuilt] = useState<any>(null);
  const [pack, setPackSel] = useState("siamese");
  const { job, start } = useJob((j) => { if (j.kind === "app" && j.status === "ok") { setBuilt(j.result); simulate(j.result.name, pack).catch(() => {}); } refresh(); });
  const fromAgent = useRef(false);

  useEffect(() => {
    fetch("/api/live").then((r) => r.json()).then((l) => { if (l.code) { setName(l.code.name); setLang(l.code.lang); setSrc(l.code.source); } });
    return onLive((e) => {
      if (e.type !== "code" || e.origin === ORIGIN) return;
      fromAgent.current = true;
      setName(e.name); setLang(e.lang); setSrc(e.source);
    });
  }, []);
  useEffect(() => {   // what is in the editor, for the agent (studio_get_code)
    if (fromAgent.current) { fromAgent.current = false; return; }
    const t = setTimeout(() => sendCode(name, lang, src), 500);
    return () => clearTimeout(t);
  }, [name, lang, src]);

  const load = (n: string) => guard(async () => {
    const s = await api.source(n);
    setName(n); setSrc(s.source); setLang(s.lang === "rs" ? "rust" : s.lang === "ts" ? "as" : s.lang);
  });

  return (
    <div className="grid2">
      <section>
        <h2>1 · Write a pet app</h2>
        <div className="row">
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="app name" />
          <select value={lang} onChange={(e) => { setLang(e.target.value); setSrc(STARTER[e.target.value]); }}>
            <option value="c">C</option><option value="zig">Zig</option><option value="rust">Rust</option><option value="as">AssemblyScript</option>
          </select>
          <select value="" onChange={(e) => e.target.value && load(e.target.value)}>
            <option value="">open example / app…</option>
            {st.apps.map((a) => <option key={a.name} value={a.name}>{a.name}</option>)}
          </select>
        </div>
        <textarea spellCheck={false} value={src} onChange={(e) => setSrc(e.target.value)} />
        <div className="row">
          <button className="primary" onClick={() => guard(async () => start((await api.buildApp(name, lang, src)).job))}>Compile to wasm → simulate</button>
          {built && <span className="dim">{built.name}.wasm · {built.bytes} B · imports {built.imports?.join(", ") || "none"}</span>}
        </div>
        <JobLog job={job} />
      </section>
      <section>
        <h2>2 · Try it here, then on the pet</h2>
        <div className="row">
          <select value={built?.name ?? ""} onChange={(e) => setBuilt(e.target.value ? { name: e.target.value } : null)}>
            <option value="">pick a built app…</option>
            {st.apps.map((a) => <option key={a.name} value={a.name}>{a.name} ({a.bytes} B)</option>)}
          </select>
          <select value={pack} onChange={(e) => { setPackSel(e.target.value); setPack(e.target.value); }}>{st.packs.map((p) => <option key={p.name}>{p.name}</option>)}</select>
          <button disabled={!built} onClick={() => built && guard(() => simulate(built.name, pack))}>▶ Simulate</button>
        </div>
        <SimScreen />
        <div className="row">
          <button className="primary" disabled={!built} onClick={() => guard(async () => start((await api.flashBle({ kind: "app", name: built.name, pet: pet || undefined })).job))}>Send to pet over BLE</button>
          <button disabled={!built} onClick={() => guard(async () => start((await api.flashBle({ kind: "run", name: built.name, pet: pet || undefined })).job))}>Run on pet</button>
          <button onClick={() => guard(async () => start((await api.flashBle({ kind: "run", name: "stop", pet: pet || undefined })).job))}>Stop app</button>
        </div>
      </section>
    </div>
  );
}

function ImageTab({ st, pet, guard, refresh }: TabProps) {
  const [name, setName] = useState("mycat");
  const [prompt, setPrompt] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [sel, setSel] = useState<string>("");
  const { job, start } = useJob((j) => { if (j.kind === "pack" && j.status === "ok") setSel(j.result.name); refresh(); });
  const pack: Pack | undefined = st.packs.find((p) => p.name === sel);
  const create = () => guard(async () => {
    if (file) {
      const b64 = await new Promise<string>((ok) => { const r = new FileReader(); r.onload = () => ok(String(r.result)); r.readAsDataURL(file); });
      start((await api.createPack({ name, imageBase64: b64, imageExt: "." + (file.name.split(".").pop() ?? "png") })).job);
    } else start((await api.createPack({ name, prompt })).job);
  });
  return (
    <div className="grid2">
      <section>
        <h2>Create a pack from one picture</h2>
        <p className="dim">A front-facing character, best on a transparent or plain background. It becomes the seven states the pet plays (96×100 GIFs). No picture? Describe one and Codex draws it (2–4 min).</p>
        <div className="row"><input value={name} onChange={(e) => setName(e.target.value)} placeholder="pack name" /></div>
        <div className="row"><input type="file" accept="image/png,image/jpeg,image/webp" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></div>
        <div className="row"><input className="wide" value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="…or describe it: a tiny orange fox with a green scarf" disabled={!!file} /></div>
        <div className="row"><button className="primary" disabled={!file && !prompt} onClick={create}>Create image pack</button></div>
        <JobLog job={job} />
      </section>
      <section>
        <h2>Packs</h2>
        <div className="packs">
          {st.packs.map((p) => (
            <button key={p.name} className={`pack ${sel === p.name ? "sel" : ""}`} onClick={() => setSel(p.name)}>
              <img src={`/api/packs/${p.name}/idle.gif`} /><span>{p.name}{p.builtIn ? "" : " ✦"}</span>
            </button>
          ))}
        </div>
        {pack && <>
          <h3>{pack.name} · {(pack.bytes / 1024).toFixed(0)} KB</h3>
          <div className="states">
            {pack.files.filter((f) => f.name.endsWith(".gif")).map((f) => (
              <figure key={f.name}><img src={`${f.url}?t=${pack.bytes}`} /><figcaption>{f.name.replace(".gif", "")}</figcaption></figure>
            ))}
          </div>
          <button className="primary" onClick={() => guard(async () => start((await api.flashBle({ kind: "pack", name: pack.name, pet: pet || undefined })).job))}>Send pack to pet over BLE</button>
        </>}
      </section>
    </div>
  );
}

function FirmwareTab({ st, pet, guard, refresh }: TabProps) {
  const [board, setBoard] = useState("sc01");
  const [pack, setPack] = useState("siamese");
  const [port, setPort] = useState("");
  const { job, start } = useJob(() => refresh());
  const bundled = st.packs.filter((p) => p.builtIn);
  return (
    <div className="grid2">
      <section>
        <h2>Firmware</h2>
        <table>
          <thead><tr><th>board</th><th>project</th><th>built</th><th>size</th></tr></thead>
          <tbody>{st.firmware.map((f) => (
            <tr key={f.board} className={board === f.board ? "sel" : ""} onClick={() => setBoard(f.board)}>
              <td>{f.label}</td><td><code>{f.project}</code></td>
              <td>{f.built ? new Date(f.built).toLocaleString() : "—"}</td><td>{f.bytes ? `${(f.bytes / 1024).toFixed(0)} KB` : ""}</td>
            </tr>))}</tbody>
        </table>
        <div className="row">
          <select value={board} onChange={(e) => setBoard(e.target.value)}>{Object.entries(st.boards).map(([k, b]) => <option key={k} value={k}>{b.label}</option>)}</select>
          <select value={pack} onChange={(e) => setPack(e.target.value)} title="the pack it boots with">{bundled.map((p) => <option key={p.name}>{p.name}</option>)}</select>
          <button className="primary" onClick={() => guard(async () => start((await api.buildFirmware(board, pack)).job))}>Build</button>
        </div>
        <h3>Flash</h3>
        <div className="row">
          <button onClick={() => guard(async () => start((await api.flashBle({ kind: "firmware", board, pet: pet || undefined })).job))}>Over BLE (OTA, keeps the pet's packs)</button>
        </div>
        <div className="row">
          <select value={port} onChange={(e) => setPort(e.target.value)}>
            <option value="">USB port…</option>{st.ports.map((p) => <option key={p}>{p}</option>)}
          </select>
          <button disabled={!port} onClick={() => guard(async () => start((await api.flashUsb(board, port)).job))}>Over USB (full: bootloader, app, packs)</button>
        </div>
        <p className="dim">BLE needs the pet to run pet firmware already (same board). USB is the first flash, and the way back from anything else.</p>
      </section>
      <section><JobLog job={job} /></section>
    </div>
  );
}

function JobsTab({ st }: { st: State }) {
  const [id, setId] = useState<string>("");
  const [job, setJob] = useState<Job | null>(null);
  useEffect(() => { if (!id) return; api.job(id).then(setJob); const t = setInterval(() => api.job(id).then(setJob), 1000); return () => clearInterval(t); }, [id]);
  return (
    <div className="grid2">
      <section>
        <h2>Jobs</h2>
        <table><tbody>{st.jobs.map((j) => (
          <tr key={j.id} className={id === j.id ? "sel" : ""} onClick={() => setId(j.id)}>
            <td><span className={`pill ${j.status}`}>{j.status}</span></td><td>{j.title}</td><td className="dim">{j.last?.slice(0, 60)}</td>
          </tr>))}</tbody></table>
      </section>
      <section><JobLog job={job} /></section>
    </div>
  );
}
