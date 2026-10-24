// Pet blocks: Blockly blocks for the desk pet's app API (lab/pet-sdk/pet.h), and a generator
// that turns a workspace into C. The C is compiled to wasm like any hand-written app, so blocks
// and code run the same way on the simulator and on the pet.
//
// Like KBIDE / DBK Screen (nat-build-with-oracle/KBProIDE): event hats, action blocks, values,
// plus Blockly's own logic, loops, maths, text and variables. Used by the page (the editor) and
// by the server (headless: MCP set_blocks -> C -> wasm), so both make the same C.
import * as Blockly from "blockly/core";
import "blockly/blocks";
import * as En from "blockly/msg/en";

export const HUE = { events: 45, pet: 200, sound: 300, values: 230, canvas: 15 };

const stmt = { previousStatement: null, nextStatement: null };
const text = (name: string) => ({ type: "input_value", name, check: ["String", "Number"] });
const num = (name: string) => ({ type: "input_value", name, check: "Number" });
const colour = (name: string) => ({ type: "input_value", name, check: ["Colour", "Number"] });
const PALETTE: [string, string][] = [
  ["⚫ black", "0,0,0"], ["⚪ white", "255,255,255"], ["🔴 red", "255,60,60"], ["🟠 orange", "255,140,40"],
  ["🟡 yellow", "255,220,40"], ["🟢 green", "60,200,90"], ["🩵 sky", "90,190,255"], ["🔵 blue", "50,90,255"],
  ["🟣 purple", "170,90,255"], ["🩷 pink", "255,120,190"], ["🩶 grey", "120,120,130"], ["🌌 navy", "10,14,40"],
];
const hat = (type: string, message0: string, args0: any[] = [], tooltip = "") => ({
  type, message0: `${message0} %${args0.length + 1} %${args0.length + 2}`,
  args0: [...args0, { type: "input_dummy" }, { type: "input_statement", name: "DO" }],
  colour: HUE.events, tooltip,
});

export const BLOCKS = [
  hat("pet_on_start", "when the app starts", [], "Runs once when the pet loads the app."),
  hat("pet_on_tap", "when the screen is tapped", [], "Replaces the pet's own heart. Use 'tap x' and 'tap y'."),
  hat("pet_every", "every %1 ms", [{ type: "field_number", name: "MS", value: 1000, min: 100, max: 600000, precision: 100 }],
    "Repeats while the app runs (the pet ticks every 100 ms)."),
  hat("pet_on_fleet", "when the agents change", [], "Each heartbeat from Desk Pet. Using it means your app decides the pet's state."),

  { type: "pet_show", message0: "show %1", colour: HUE.pet, ...stmt,
    args0: [{ type: "field_dropdown", name: "STATE", options: [["idle", "PET_IDLE"], ["busy", "PET_BUSY"], ["attention", "PET_ATTENTION"], ["sleep", "PET_SLEEP"]] }] },
  { type: "pet_react", message0: "show the heart ❤️", colour: HUE.pet, ...stmt },
  { type: "pet_caption", message0: "caption %1", args0: [text("TEXT")], colour: HUE.pet, ...stmt, tooltip: "The line under the pet (20 characters)." },
  { type: "pet_status", message0: "status line %1", args0: [text("TEXT")], colour: HUE.pet, ...stmt, tooltip: "The HUD line at the bottom." },
  { type: "pet_pack", message0: "switch pack to %1", args0: [{ type: "field_input", name: "NAME", text: "siamese" }], colour: HUE.pet, ...stmt },
  { type: "pet_say", message0: "say %1", args0: [text("TEXT")], colour: HUE.pet, ...stmt, tooltip: "OraclePet turns it into the pet's voice." },
  { type: "pet_log", message0: "log %1", args0: [text("TEXT")], colour: HUE.pet, ...stmt, tooltip: "The serial console." },

  { type: "pet_sound", message0: "play %1", colour: HUE.sound, ...stmt,
    args0: [{ type: "field_dropdown", name: "KIND", options: [["ribbit 🐸", "PET_RIBBIT"], ["blip up", "PET_BLIP_UP"], ["blip down", "PET_BLIP_DOWN"]] }] },
  { type: "pet_tone", message0: "tone %1 Hz for %2 ms", args0: [num("HZ"), num("MS")], inputsInline: true, colour: HUE.sound, ...stmt },

  // canvas mode: the app draws the screen (the area above the HUD) instead of the cat
  { type: "pet_canvas", message0: "%1", colour: HUE.canvas, ...stmt, tooltip: "Canvas mode: your drawing replaces the cat. Frame mode: the cat again.",
    args0: [{ type: "field_dropdown", name: "ON", options: [["canvas mode 🎨", "1"], ["frame mode 🐱", "0"]] }] },
  { type: "pet_clear", message0: "fill the screen %1", args0: [colour("C")], colour: HUE.canvas, ...stmt },
  { type: "pet_rect", message0: "rectangle x %1 y %2 w %3 h %4 %5", args0: [num("X"), num("Y"), num("W"), num("H"), colour("C")], inputsInline: true, colour: HUE.canvas, ...stmt },
  { type: "pet_circle", message0: "circle x %1 y %2 radius %3 %4", args0: [num("X"), num("Y"), num("R"), colour("C")], inputsInline: true, colour: HUE.canvas, ...stmt },
  { type: "pet_line", message0: "line %1 , %2 to %3 , %4 %5", args0: [num("X0"), num("Y0"), num("X1"), num("Y1"), colour("C")], inputsInline: true, colour: HUE.canvas, ...stmt },
  { type: "pet_text", message0: "write %1 at x %2 y %3 size %4 %5", args0: [text("TEXT"), num("X"), num("Y"), num("S"), colour("C")], inputsInline: true, colour: HUE.canvas, ...stmt,
    tooltip: "8 x 8 letters times the size; ASCII only." },
  { type: "pet_colour", message0: "%1", args0: [{ type: "field_dropdown", name: "C", options: PALETTE }], output: "Colour", colour: HUE.canvas },
  { type: "pet_rgb", message0: "colour r %1 g %2 b %3", args0: [num("R"), num("G"), num("B")], inputsInline: true, output: "Colour", colour: HUE.canvas },
  { type: "pet_size", message0: "screen %1", args0: [{ type: "field_dropdown", name: "WHICH", options: [["width", "w"], ["height", "h"]] }], output: "Number", colour: HUE.canvas },

  { type: "pet_millis", message0: "time since start (ms)", output: "Number", colour: HUE.values },
  { type: "pet_tap", message0: "tap %1", args0: [{ type: "field_dropdown", name: "AXIS", options: [["x", "x"], ["y", "y"]] }], output: "Number", colour: HUE.values },
  { type: "pet_fleet", message0: "agents %1", output: "Number", colour: HUE.values,
    args0: [{ type: "field_dropdown", name: "WHICH", options: [["total", "total"], ["running", "running"], ["waiting", "waiting"]] }] },
  { type: "pet_join", message0: "join %1 %2", args0: [{ type: "input_value", name: "A" }, { type: "input_value", name: "B" }], inputsInline: true,
    output: "String", colour: HUE.values, tooltip: "Text and numbers together, e.g. join 'taps: ' 3." },
];

let installed = false;
export function installBlocks() {
  if (installed) return;
  installed = true;
  Blockly.setLocale(En as any);   // the built-in blocks' text (math_change, controls_if...) comes from the messages
  Blockly.common.defineBlocksWithJsonArray(BLOCKS as any[]);
}

// ---- the C generator ----
const O = { ATOMIC: 0, CALL: 1, UNARY: 2, MULT: 3, ADD: 4, REL: 6, EQ: 7, AND: 11, OR: 12, NONE: 99 };
type Ctx = { vars: Map<string, string>; loop: number };
const ctx: Ctx = { vars: new Map(), loop: 0 };

export const gen = new Blockly.CodeGenerator("PetC");
gen.INDENT = "    ";
gen.scrub_ = function (block: Blockly.Block, code: string, thisOnly?: boolean) {
  const next = block.nextConnection?.targetBlock();
  return code + (next && !thisOnly ? gen.blockToCode(next) : "");
};

const cstr = (s: string) => '"' + s.replace(/\\/g, "\\\\").replace(/"/g, '\\"').replace(/\n/g, "\\n") + '"';
/** A value input as a C string: text stays text, anything numeric goes through ps_num(). */
function strIn(b: Blockly.Block, name: string): string {
  const t = b.getInputTargetBlock(name);
  if (!t) return '""';
  const code = gen.valueToCode(b, name, O.NONE) || '""';
  const out = t.outputConnection?.getCheck();
  return out && out.includes("String") && !out.includes("Number") ? code : `ps_num(${code})`;
}
const numIn = (b: Blockly.Block, name: string, dflt = "0") => gen.valueToCode(b, name, O.NONE) || dflt;
const varName = (b: Blockly.Block) => ctx.vars.get(b.getFieldValue("VAR")) ?? "v_unknown";
const f = gen.forBlock as Record<string, (b: Blockly.Block) => string | [string, number]>;

f.pet_show = (b) => `pet_show(${b.getFieldValue("STATE")});\n`;
f.pet_react = () => "pet_react();\n";
f.pet_caption = (b) => `pet_caption(${strIn(b, "TEXT")});\n`;
f.pet_status = (b) => `pet_status(${strIn(b, "TEXT")});\n`;
f.pet_pack = (b) => `pet_pack(${cstr(String(b.getFieldValue("NAME") ?? ""))});\n`;
f.pet_say = (b) => `pet_say(${strIn(b, "TEXT")});\n`;
f.pet_log = (b) => `pet_log(${strIn(b, "TEXT")});\n`;
f.pet_sound = (b) => `pet_sound(${b.getFieldValue("KIND")});\n`;
f.pet_tone = (b) => `pet_tone(${numIn(b, "HZ", "440")}, ${numIn(b, "MS", "200")});\n`;
f.pet_canvas = (b) => `pet_canvas(${b.getFieldValue("ON") === "0" ? 0 : 1});\n`;
const col = (b: Blockly.Block, name: string) => gen.valueToCode(b, name, O.NONE) || "0";
f.pet_clear = (b) => `pet_clear(${col(b, "C")});\n`;
f.pet_rect = (b) => `pet_rect(${numIn(b, "X")}, ${numIn(b, "Y")}, ${numIn(b, "W", "10")}, ${numIn(b, "H", "10")}, ${col(b, "C")});\n`;
f.pet_circle = (b) => `pet_circle(${numIn(b, "X")}, ${numIn(b, "Y")}, ${numIn(b, "R", "10")}, ${col(b, "C")});\n`;
f.pet_line = (b) => `pet_line(${numIn(b, "X0")}, ${numIn(b, "Y0")}, ${numIn(b, "X1")}, ${numIn(b, "Y1")}, ${col(b, "C")});\n`;
f.pet_text = (b) => `pet_text(${numIn(b, "X")}, ${numIn(b, "Y")}, ${numIn(b, "S", "2")}, ${col(b, "C")}, ${strIn(b, "TEXT")});\n`;
f.pet_colour = (b) => [`pet_rgb(${b.getFieldValue("C")})`, O.CALL];
f.pet_rgb = (b) => [`pet_rgb(${numIn(b, "R")}, ${numIn(b, "G")}, ${numIn(b, "B")})`, O.CALL];
f.pet_size = (b) => [b.getFieldValue("WHICH") === "h" ? "pet_height()" : "pet_width()", O.CALL];
f.pet_millis = () => ["pet_millis()", O.CALL];
f.pet_tap = (b) => [b.getFieldValue("AXIS") === "y" ? "ps_tap_y" : "ps_tap_x", O.ATOMIC];
f.pet_fleet = (b) => [`ps_${b.getFieldValue("WHICH")}`, O.ATOMIC];
f.pet_join = (b) => [`ps_join(${strIn(b, "A")}, ${strIn(b, "B")})`, O.CALL];

f.text = (b) => [cstr(String(b.getFieldValue("TEXT") ?? "")), O.ATOMIC];
f.math_number = (b) => [String(Math.trunc(Number(b.getFieldValue("NUM")) || 0)), O.ATOMIC];
f.math_arithmetic = (b) => {
  const op = { ADD: ["+", O.ADD], MINUS: ["-", O.ADD], MULTIPLY: ["*", O.MULT], DIVIDE: ["/", O.MULT], POWER: ["*", O.MULT] }[b.getFieldValue("OP") as string] as [string, number];
  const a = gen.valueToCode(b, "A", op[1]) || "0", c = gen.valueToCode(b, "B", op[1]) || "0";
  if (op[0] === "/") return [`ps_div(${a}, ${c})`, O.CALL];
  return [`${a} ${op[0]} ${c}`, op[1]];
};
f.math_modulo = (b) => [`ps_mod(${numIn(b, "DIVIDEND")}, ${numIn(b, "DIVISOR", "1")})`, O.CALL];
f.math_random_int = (b) => [`ps_rand(${numIn(b, "FROM")}, ${numIn(b, "TO", "10")})`, O.CALL];
f.logic_boolean = (b) => [b.getFieldValue("BOOL") === "TRUE" ? "1" : "0", O.ATOMIC];
f.logic_negate = (b) => [`!${gen.valueToCode(b, "BOOL", O.UNARY) || "0"}`, O.UNARY];
f.logic_compare = (b) => {
  const op = { EQ: "==", NEQ: "!=", LT: "<", LTE: "<=", GT: ">", GTE: ">=" }[b.getFieldValue("OP") as string]!;
  const order = op === "==" || op === "!=" ? O.EQ : O.REL;
  return [`${gen.valueToCode(b, "A", order) || "0"} ${op} ${gen.valueToCode(b, "B", order) || "0"}`, order];
};
f.logic_operation = (b) => {
  const and = b.getFieldValue("OP") === "AND", order = and ? O.AND : O.OR;
  return [`${gen.valueToCode(b, "A", order) || "0"} ${and ? "&&" : "||"} ${gen.valueToCode(b, "B", order) || "0"}`, order];
};
f.controls_if = (b) => {
  let code = "", n = 0;
  do {
    const cond = gen.valueToCode(b, "IF" + n, O.NONE) || "0";
    code += `${n ? " else " : ""}if (${cond}) {\n${gen.statementToCode(b, "DO" + n)}}`;
    n++;
  } while (b.getInput("IF" + n));
  if (b.getInput("ELSE")) code += ` else {\n${gen.statementToCode(b, "ELSE")}}`;
  return code + "\n";
};
f.controls_repeat_ext = (b) => {
  const i = `i${ctx.loop++}`;
  return `for (int ${i} = 0; ${i} < ${numIn(b, "TIMES", "0")}; ${i}++) {\n${gen.statementToCode(b, "DO")}}\n`;
};
f.controls_whileUntil = (b) => {
  const until = b.getFieldValue("MODE") === "UNTIL";
  const cond = gen.valueToCode(b, "BOOL", until ? O.UNARY : O.NONE) || "0";
  return `for (int guard = 0; ${until ? `!${cond}` : cond} && guard < 10000; guard++) {\n${gen.statementToCode(b, "DO")}}\n`;
};
f.variables_get = (b) => [varName(b), O.ATOMIC];
f.variables_set = (b) => `${varName(b)} = ${numIn(b, "VALUE")};\n`;
f.math_change = (b) => `${varName(b)} += ${numIn(b, "DELTA", "1")};\n`;

const HELPERS = `static char ps_buf[4][48];
static int ps_bi;
static int ps_tap_x, ps_tap_y, ps_total, ps_running, ps_waiting;
static unsigned ps_seed;
__attribute__((unused)) static const char *ps_num(int v) { char *b = ps_buf[ps_bi++ & 3]; int at = 0; pet_put_int(b, &at, v); return b; }
__attribute__((unused)) static const char *ps_join(const char *a, const char *b)
{
    char *o = ps_buf[ps_bi++ & 3]; int n = 0;
    while (*a && n < 47) o[n++] = *a++;
    while (*b && n < 47) o[n++] = *b++;
    o[n] = 0; return o;
}
__attribute__((unused)) static int ps_div(int a, int b) { return b ? a / b : 0; }
__attribute__((unused)) static int ps_mod(int a, int b) { return b ? a % b : 0; }
__attribute__((unused)) static int ps_rand(int lo, int hi)
{
    if (!ps_seed) ps_seed = 2463534242u ^ (unsigned)pet_millis();
    ps_seed ^= ps_seed << 13; ps_seed ^= ps_seed >> 17; ps_seed ^= ps_seed << 5;
    if (hi < lo) { int t = lo; lo = hi; hi = t; }
    return lo + (int)(ps_seed % (unsigned)(hi - lo + 1));
}
`;

/** C for a workspace. Blocks outside an event hat do nothing, as in Scratch and DBK Screen. */
export function workspaceToC(ws: Blockly.Workspace, name = "blocks"): string {
  gen.init(ws);
  ctx.vars = new Map();
  ctx.loop = 0;
  const used = new Set<string>();
  for (const v of ws.getVariableMap().getAllVariables()) {
    let id = "v_" + (v.getName().normalize("NFKD").replace(/[^A-Za-z0-9_]/g, "_").replace(/^_+|_+$/g, "") || "var");
    while (used.has(id)) id += "_";
    used.add(id);
    ctx.vars.set(v.getId(), id);
  }
  const start: string[] = [], tap: string[] = [], fleet: string[] = [], every: [number, string][] = [];
  for (const top of ws.getTopBlocks(true)) {
    if (!top.isEnabled()) continue;
    const body = gen.statementToCode(top, "DO");
    if (top.type === "pet_on_start") start.push(body);
    else if (top.type === "pet_on_tap") tap.push(body);
    else if (top.type === "pet_on_fleet") fleet.push(body);
    else if (top.type === "pet_every") every.push([Math.max(100, Number(top.getFieldValue("MS")) || 1000), body]);
  }
  const out: string[] = [
    `// ${name}: generated by Pet Studio from blocks. Edit the blocks; this file is rewritten.`,
    `#include "pet.h"`, "", HELPERS,
  ];
  if (ctx.vars.size) out.push([...ctx.vars.values()].map((v) => `static int ${v};`).join("\n"), "");
  // drawing blocks without a mode block: the app means canvas mode, so it starts in it
  const draws = ws.getAllBlocks(false).some((b) => DRAW.has(b.type) && b.isEnabled());
  const modeSet = ws.getAllBlocks(false).some((b) => b.type === "pet_canvas" && b.isEnabled());
  const pre = draws && !modeSet ? "    pet_canvas(1);\n" : "";
  out.push(`PET_EXPORT("on_start") void on_start(void)\n{\n${pre}${start.join("")}}\n`);
  if (tap.length) out.push(`PET_EXPORT("on_tap") void on_tap(int x, int y)\n{\n    ps_tap_x = x; ps_tap_y = y;\n${tap.join("")}}\n`);
  if (fleet.length) out.push(`PET_EXPORT("on_fleet") void on_fleet(int total, int running, int waiting)\n{\n    ps_total = total; ps_running = running; ps_waiting = waiting;\n${fleet.join("")}}\n`);
  if (every.length) {
    out.push(`PET_EXPORT("on_tick") void on_tick(int ms)\n{\n` + every.map(([ms, body], i) =>
      `    static int last${i};\n    if (ms - last${i} >= ${ms}) {\n        last${i} = ms;\n${body.replace(/^/gm, "    ").replace(/^ +$/gm, "")}    }\n`).join("") + "}\n");
  }
  return out.join("\n");
}

const DRAW = new Set(["pet_clear", "pet_rect", "pet_circle", "pet_line", "pet_text"]);
/** Canvas mode if the program draws (the editor's Frame / Canvas switch follows this). */
export function isCanvasProgram(state: any): boolean {
  return JSON.stringify(state ?? {}).match(/"type":"pet_(clear|rect|circle|line|text|canvas)"/) !== null;
}

/** Headless: blocks JSON (Blockly.serialization.workspaces.save) -> C. Throws on blocks it does not know. */
export function blocksToC(state: object, name = "blocks"): string {
  installBlocks();
  const ws = new Blockly.Workspace();
  try {
    Blockly.serialization.workspaces.load(state as any, ws);
    return workspaceToC(ws, name);
  } finally { ws.dispose(); }
}

/** Every block type the generator handles (the toolbox below, and what MCP set_blocks accepts). */
export const SUPPORTED = Object.keys(gen.forBlock).sort();

// ---- toolbox ----
const sh = (type: string, fields: object) => ({ shadow: { type, fields } });
const N = (v: number) => sh("math_number", { NUM: v });
const T = (v: string) => sh("text", { TEXT: v });
const b = (type: string, inputs?: object, fields?: object) => ({ kind: "block", type, ...(inputs ? { inputs } : {}), ...(fields ? { fields } : {}) });
const cat = (name: string, colour: number | string, contents: any[]) => ({ kind: "category", name, colour: String(colour), contents });

const C = (v: string) => ({ shadow: { type: "pet_colour", fields: { C: v } } });
const events = cat("Events", HUE.events, [b("pet_on_start"), b("pet_on_tap"), b("pet_every"), b("pet_on_fleet")]);
const petCat = cat("Pet", HUE.pet, [
  b("pet_show"), b("pet_react"), b("pet_caption", { TEXT: T("hello!") }), b("pet_status", { TEXT: T("app: blocks") }),
  b("pet_pack"), b("pet_say", { TEXT: T("hello") }), b("pet_log", { TEXT: T("hi") }),
]);
const canvasCat = cat("Canvas", HUE.canvas, [
  b("pet_canvas"), b("pet_clear", { C: C("10,14,40") }),
  b("pet_circle", { X: N(160), Y: N(200), R: N(40), C: C("255,220,40") }),
  b("pet_rect", { X: N(20), Y: N(20), W: N(120), H: N(60), C: C("255,120,190") }),
  b("pet_line", { X0: N(0), Y0: N(60), X1: N(320), Y1: N(60), C: C("255,255,255") }),
  b("pet_text", { TEXT: T("hello"), X: N(20), Y: N(30), S: N(3), C: C("255,255,255") }),
  b("pet_colour"), b("pet_rgb", { R: N(255), G: N(128), B: N(0) }), b("pet_size"),
]);
const rest = [
  cat("Sound", HUE.sound, [b("pet_sound"), b("pet_tone", { HZ: N(880), MS: N(150) })]),
  cat("Values", HUE.values, [b("pet_millis"), b("pet_tap"), b("pet_fleet"), b("pet_join", { A: T("taps: "), B: N(0) }), b("text"), b("math_number")]),
  cat("Logic", 210, [b("controls_if"), b("logic_compare"), b("logic_operation"), b("logic_negate"), b("logic_boolean")]),
  cat("Loops", 120, [b("controls_repeat_ext", { TIMES: N(3) }), b("controls_whileUntil")]),
  cat("Maths", 230, [b("math_arithmetic", { A: N(1), B: N(1) }), b("math_modulo", { DIVIDEND: N(10), DIVISOR: N(3) }), b("math_random_int", { FROM: N(1), TO: N(6) })]),
  { kind: "category", name: "Variables", colour: "330", custom: "VARIABLE" },
];
/** Frame mode: the pet plays its pack's GIFs and the app picks the state, caption and sounds. */
export const TOOLBOX = { kind: "categoryToolbox", contents: [events, petCat, ...rest] };
/** Canvas mode: the app draws the screen itself (the cat pauses). */
export const CANVAS_TOOLBOX = { kind: "categoryToolbox", contents: [events, canvasCat, petCat, ...rest] };

// ---- a first program ----
export const EXAMPLE = {
  blocks: {
    languageVersion: 0,
    blocks: [
      { type: "pet_on_start", x: 20, y: 20, inputs: { DO: { block: {
        type: "pet_caption", inputs: { TEXT: { shadow: { type: "text", fields: { TEXT: "tap me!" } } } },
        next: { block: { type: "pet_status", inputs: { TEXT: { shadow: { type: "text", fields: { TEXT: "app: blocks" } } } } } } } } } },
      { type: "pet_on_tap", x: 20, y: 170, inputs: { DO: { block: {
        type: "math_change", fields: { VAR: { id: "taps" } }, inputs: { DELTA: { shadow: { type: "math_number", fields: { NUM: 1 } } } },
        next: { block: { type: "pet_caption", inputs: { TEXT: { block: { type: "pet_join", inputs: {
          A: { shadow: { type: "text", fields: { TEXT: "taps: " } } }, B: { block: { type: "variables_get", fields: { VAR: { id: "taps" } } } } } } } },
        next: { block: { type: "pet_sound", fields: { KIND: "PET_BLIP_UP" },
        next: { block: { type: "controls_if", inputs: {
          IF0: { block: { type: "logic_compare", fields: { OP: "EQ" }, inputs: {
            A: { block: { type: "math_modulo", inputs: { DIVIDEND: { block: { type: "variables_get", fields: { VAR: { id: "taps" } } } }, DIVISOR: { shadow: { type: "math_number", fields: { NUM: 3 } } } } } },
            B: { shadow: { type: "math_number", fields: { NUM: 0 } } } } } },
          DO0: { block: { type: "pet_react" } } } } } } } } } } } } },
      { type: "pet_every", x: 20, y: 470, fields: { MS: 5000 }, inputs: { DO: { block: { type: "pet_show", fields: { STATE: "PET_IDLE" } } } } },
    ],
  },
  variables: [{ name: "taps", id: "taps" }],
};

// ---- a first canvas program: a ball that bounces, a tap moves it ----
const nv = (id: string) => ({ block: { type: "variables_get", fields: { VAR: { id } } } });
const setv = (id: string, value: object, next?: object) => ({ type: "variables_set", fields: { VAR: { id } }, inputs: { VALUE: value }, ...(next ? { next: { block: next } } : {}) });
const add = (a: object, bb: object) => ({ block: { type: "math_arithmetic", fields: { OP: "ADD" }, inputs: { A: a, B: bb } } });
const num_ = (v: number) => ({ shadow: { type: "math_number", fields: { NUM: v } } });
const bounce = (pos: string, vel: string, lo: number, hiField: "w" | "h") => ({
  type: "controls_if", inputs: {
    IF0: { block: { type: "logic_operation", fields: { OP: "OR" }, inputs: {
      A: { block: { type: "logic_compare", fields: { OP: "LT" }, inputs: { A: nv(pos), B: num_(lo) } } },
      B: { block: { type: "logic_compare", fields: { OP: "GT" }, inputs: { A: nv(pos),
        B: { block: { type: "math_arithmetic", fields: { OP: "MINUS" }, inputs: { A: { block: { type: "pet_size", fields: { WHICH: hiField } } }, B: num_(20) } } } } } } } } },
    DO0: { block: setv(vel, { block: { type: "math_arithmetic", fields: { OP: "MULTIPLY" }, inputs: { A: nv(vel), B: num_(-1) } } }) } } });
const drawBall = (next?: object) => ({ type: "pet_clear", inputs: { C: C("10,14,40") }, next: { block: {
  type: "pet_circle", inputs: { X: nv("x"), Y: nv("y"), R: num_(20), C: C("255,140,40") }, next: { block: {
  type: "pet_text", inputs: { TEXT: { block: { type: "pet_join", inputs: { A: T("taps "), B: nv("taps") } } }, X: num_(10), Y: num_(12), S: num_(2), C: C("255,255,255") },
  ...(next ? { next: { block: next } } : {}) } } } } });

export const CANVAS_EXAMPLE = {
  blocks: {
    languageVersion: 0,
    blocks: [
      { type: "pet_on_start", x: 20, y: 20, inputs: { DO: { block: { type: "pet_canvas", fields: { ON: "1" }, next: { block:
        setv("x", num_(60), setv("y", num_(80), setv("dx", num_(7), setv("dy", num_(5), { type: "pet_status", inputs: { TEXT: T("app: canvas blocks") } }))))
      } } } } },
      { type: "pet_every", x: 20, y: 260, fields: { MS: 100 }, inputs: { DO: { block:
        setv("x", add(nv("x"), nv("dx")), setv("y", add(nv("y"), nv("dy")), { ...bounce("x", "dx", 20, "w"), next: { block: { ...bounce("y", "dy", 20, "h"), next: { block: drawBall() } } } }))
      } } },
      { type: "pet_on_tap", x: 20, y: 620, inputs: { DO: { block: {
        type: "math_change", fields: { VAR: { id: "taps" } }, inputs: { DELTA: num_(1) }, next: { block:
        setv("x", { block: { type: "pet_tap", fields: { AXIS: "x" } } }, setv("y", { block: { type: "pet_tap", fields: { AXIS: "y" } } }, { type: "pet_sound", fields: { KIND: "PET_BLIP_UP" } })) } } } } },
    ],
  },
  variables: ["x", "y", "dx", "dy", "taps"].map((id) => ({ name: id, id })),
};
