// Blocks, like KBIDE / DBK Screen: the pet's API as Blockly blocks, C generated live beside them,
// then compiled to wasm, run in the simulator and sent to the pet. The agent edits the same
// workspace over MCP (studio_set_blocks / studio_get_blocks): its changes appear here live.
import { useEffect, useRef, useState } from "react";
import * as Blockly from "blockly/core";
import { CANVAS_EXAMPLE, CANVAS_TOOLBOX, EXAMPLE, installBlocks, isCanvasProgram, TOOLBOX, workspaceToC } from "../../shared/petblocks";
import { api, type State } from "./api";
import { onLive, sendBlocks, ORIGIN } from "./live";
import { SimScreen } from "./SimScreen";
import { simulate } from "./simstore";

/** Load blocks without firing change events. Blockly fires them after a timeout, so a flag set
 * around load() missed them, and two open pages echoed each other's blocks forever. */
function quietLoad(w: Blockly.WorkspaceSvg, blocks: object) {
  Blockly.Events.disable();
  try {
    Blockly.serialization.workspaces.load(blocks as any, w);
    w.cleanUp();                                  // one column, no hat on top of another
  } finally { Blockly.Events.enable(); }
}

/** Blockly in the page's dark palette (the default panel is light grey under light text). */
const DARK = Blockly.Theme.defineTheme("pet-dark", {
  name: "pet-dark",
  base: Blockly.Themes.Classic,
  componentStyles: {
    workspaceBackgroundColour: "#12151b", toolboxBackgroundColour: "#171a21", toolboxForegroundColour: "#e6e6e6",
    flyoutBackgroundColour: "#1f232c", flyoutForegroundColour: "#cfd3dc", flyoutOpacity: 0.96,
    scrollbarColour: "#3a4050", scrollbarOpacity: 0.7, insertionMarkerColour: "#f2b544", markerColour: "#f2b544",
    cursorColour: "#f2b544", selectedGlowColour: "#f2b544",
  },
  fontStyle: { family: "-apple-system, BlinkMacSystemFont, sans-serif", weight: "600", size: 11 },
  startHats: true,
});

type Mode = "frame" | "canvas";
const MODES: { id: Mode; label: string; hint: string }[] = [
  { id: "frame", label: "🐱 Frame mode", hint: "the pet plays its pack's GIF frames; blocks pick the state, caption and sounds" },
  { id: "canvas", label: "🎨 Canvas mode", hint: "the blocks draw the whole screen above the HUD: shapes, text, colours" },
];

type Props = { st: State; pet: string; guard: (f: () => Promise<void>) => Promise<void>; refresh: () => void;
  start: (job: string) => void; jobLog: React.ReactNode };

export function BlocksTab({ st, pet, guard, start, jobLog }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const ws = useRef<Blockly.WorkspaceSvg | null>(null);
  const applying = useRef(false);
  const lastSent = useRef("");   // the blocks last sent or received: an identical save is not sent again
  const [name, setName] = useState("blocks");
  const [c, setC] = useState("");
  const [by, setBy] = useState("");
  const [mode, setModeState] = useState<Mode>("frame");
  const modeRef = useRef<Mode>("frame");
  const applyMode = (m: Mode) => { modeRef.current = m; setModeState(m); ws.current?.updateToolbox((m === "canvas" ? CANVAS_TOOLBOX : TOOLBOX) as any); };
  const nameRef = useRef(name);
  nameRef.current = name;

  useEffect(() => {
    installBlocks();
    const w = Blockly.inject(host.current!, {
      toolbox: TOOLBOX as any, renderer: "zelos", theme: DARK,
      grid: { spacing: 24, length: 2, colour: "#2a2f3a", snap: true },
      zoom: { controls: true, wheel: true, startScale: 0.75, maxScale: 2, minScale: 0.3 }, trashcan: true,
    });
    ws.current = w;
    (window as any).__petWorkspace = w;
    const ro = new ResizeObserver(() => Blockly.svgResize(w));
    ro.observe(host.current!);
    const load = (blocks: object) => {
      quietLoad(w, blocks);
      lastSent.current = JSON.stringify(Blockly.serialization.workspaces.save(w));
      setC(workspaceToC(w, nameRef.current));
      const m: Mode = isCanvasProgram(blocks) ? "canvas" : "frame";
      if (m !== modeRef.current) applyMode(m);
    };
    fetch("/api/live").then((r) => r.json()).then((l) => { setName(l.name); nameRef.current = l.name; load(l.blocks); });
    let t = 0;
    w.addChangeListener((e) => {
      if (applying.current || e.isUiEvent) return;
      clearTimeout(t);
      t = window.setTimeout(() => {
        setC(workspaceToC(w, nameRef.current));
        const save = Blockly.serialization.workspaces.save(w), key = JSON.stringify(save);
        if (key === lastSent.current) return;     // nothing really changed (a move by 0, a reload)
        lastSent.current = key;
        sendBlocks(nameRef.current, save);
        setBy("you");
      }, 350);
    });
    const off = onLive((e) => {
      if (e.type === "blocks" && e.origin !== ORIGIN) { if (e.name) { setName(e.name); nameRef.current = e.name; } load(e.blocks); setBy("the agent"); }
    });
    return () => { off(); ro.disconnect(); w.dispose(); ws.current = null; };
  }, []);

  const switchMode = (m: Mode) => {
    if (m === mode) return;
    applyMode(m);
    const w = ws.current!;
    const fresh = w.getAllBlocks(false).length === 0;
    if (fresh || window.confirm(`Start from the ${m} mode example? (Cancel keeps your blocks; the toolbox changes either way.)`)) {
      quietLoad(w, m === "canvas" ? CANVAS_EXAMPLE : EXAMPLE);
      lastSent.current = JSON.stringify(Blockly.serialization.workspaces.save(w));
      const n = m === "canvas" ? "canvas-blocks" : "blocks";
      setName(n); nameRef.current = n;
      setC(workspaceToC(w, n));
      sendBlocks(n, Blockly.serialization.workspaces.save(w));
    }
  };

  const compile = () => guard(async () => {
    const w = ws.current!;
    await sendBlocks(name, Blockly.serialization.workspaces.save(w));
    const r = await fetch("/api/blocks/build", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ name, origin: ORIGIN }) }).then((x) => x.json());
    if (r.error) throw new Error(r.error);
    start(r.job);
  });

  return (
    <div className="blocks-grid">
      <section className="blocks-main">
        <div className="mb-2 flex flex-wrap items-center gap-3">
          <div className="inline-flex overflow-hidden rounded-lg border border-line">
            {MODES.map((m) => (
              <button key={m.id} onClick={() => switchMode(m.id)} title={m.hint}
                className={`rounded-none border-0 px-4 py-1.5 whitespace-nowrap ${mode === m.id ? "bg-accent font-semibold text-[#1b1b1b]" : "bg-[#232733] text-[#e6e6e6] hover:bg-line"}`}>{m.label}</button>
            ))}
          </div>
          <span className="text-xs text-dim">{MODES.find((m) => m.id === mode)!.hint}</span>
        </div>
        <div className="row">
          <input value={name} onChange={(e) => setName(e.target.value.toLowerCase())} placeholder="app name" />
          <button className="primary" onClick={compile}>Compile blocks → wasm → simulate</button>
          <button disabled={!st.apps.some((a) => a.name === name)} title="compile first" onClick={() => guard(async () => start((await api.flashBle({ kind: "app", name, pet: pet || undefined })).job))}>Send to pet over BLE</button>
          {by && <span className="dim">last change by {by}</span>}
        </div>
        <div ref={host} className="blockly" />
      </section>
      <section>
        <h2>Simulator</h2>
        <SimScreen />
        <div className="row"><button onClick={() => guard(() => simulate(name))}>▶ Run {name} again</button></div>
        {jobLog}
      </section>
      <section className="cpreview">
        <h2>C from the blocks</h2>
        <pre>{c}</pre>
        <p className="dim">{st.apps.find((a) => a.name === name) ? `${name}.wasm built` : "not compiled yet"}</p>
      </section>
    </div>
  );
}
