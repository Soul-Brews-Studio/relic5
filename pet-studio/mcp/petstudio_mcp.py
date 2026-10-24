# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=1.2,<2"]   # 2.x renamed FastMCP
# ///
"""petstudio MCP server: an agent makes things for the desk pet and puts them on it.

It is a thin client of the pet-studio server (../server/index.ts, http://127.0.0.1:4810), the same
API the web page uses, so a person watching the page sees the agent's jobs arrive. If the server is
not up, the first tool call starts it (bun, logging to /tmp/pet-studio.log).

    claude mcp add petstudio -- uv run --script pet-studio/mcp/petstudio_mcp.py   (from the relic5 checkout)

Every tool that starts a job waits for it and returns its result plus the end of its log.

Live tools (studio_get_blocks, studio_set_blocks, studio_get_code, studio_set_code, studio_screen,
studio_tap, studio_simulate) work on the page open at http://127.0.0.1:4810, the way droidcast
mirrors a phone: what the agent sets appears in the page at once, and what a person builds there
the agent can read back.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from mcp.server.fastmcp import FastMCP, Image

BASE = os.environ.get("PET_STUDIO_URL", "http://127.0.0.1:4810")
STUDIO = Path(__file__).resolve().parent.parent
mcp = FastMCP("petstudio")


def _req(path: str, body: dict | None = None, timeout: float = 15) -> dict:
    data = None if body is None else json.dumps(body).encode()
    r = urllib.request.Request(BASE + path, data=data, headers={"content-type": "application/json"},
                               method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(json.loads(e.read() or b"{}").get("error") or str(e)) from None


def _ensure_server() -> None:
    try:
        _req("/api/health", timeout=2)
        return
    except Exception:
        pass
    bun = os.environ.get("BUN", str(Path.home() / ".bun/bin/bun"))
    log = open("/tmp/pet-studio.log", "a")
    subprocess.Popen([bun, "server/index.ts"], cwd=STUDIO, stdout=log, stderr=log, start_new_session=True)
    for _ in range(40):
        time.sleep(0.25)
        try:
            _req("/api/health", timeout=2)
            return
        except Exception:
            pass
    raise RuntimeError("pet-studio server did not start (see /tmp/pet-studio.log)")


def _run(path: str, body: dict, timeout: float) -> dict:
    """Start a job and wait for it: {status, result | error, log (last lines), seconds}."""
    _ensure_server()
    jid = _req(path, body)["job"]
    end = time.time() + timeout
    while time.time() < end:
        j = _req(f"/api/jobs/{jid}")
        if j["status"] in ("ok", "failed"):
            out = {"job": jid, "status": j["status"], "title": j["title"],
                   "seconds": round(((j.get("ended") or 0) - j["started"]) / 1000, 1),
                   "log": j["log"][-15:]}
            out["result" if j["status"] == "ok" else "error"] = j.get("result") if j["status"] == "ok" else j.get("error")
            return out
        time.sleep(1)
    return {"job": jid, "status": "still running", "hint": f"call studio_job('{jid}') later"}


@mcp.tool()
def studio_state() -> dict:
    """What the studio sees: OraclePet and the pets it links (name, link, firmware, pack, app, last
    transfer), USB ports, built firmware per board, built wasm apps, image packs, recent jobs."""
    _ensure_server()
    s = _req("/api/state")
    s.pop("boards", None)
    s["packs"] = [{"name": p["name"], "builtIn": p["builtIn"], "kb": round(p["bytes"] / 1024)} for p in s["packs"]]
    return s


@mcp.tool()
def studio_build_app(name: str, source: str, lang: str = "c") -> dict:
    """Compile a pet app to WebAssembly with lab/pet-sdk (then load-check it in the pet's own WAMR).
    `name`: a-z 0-9 - _ (max 23). `lang`: c, zig, rust or as (AssemblyScript). C apps
    `#include "pet.h"` and export on_start / on_tick(ms) / on_tap(x, y) / on_fleet(total, running,
    waiting) with PET_EXPORT("..."); they call pet_caption, pet_status, pet_show(PET_IDLE|BUSY|
    ATTENTION|SLEEP), pet_react, pet_pack, pet_sound, pet_tone, pet_say, pet_log. Returns the wasm
    size, imports and exports; the page at http://127.0.0.1:4810 can simulate it."""
    return _run("/api/apps/build", {"name": name, "source": source, "lang": lang}, 180)


@mcp.tool()
def studio_create_pack(name: str, image_path: str | None = None, prompt: str | None = None) -> dict:
    """Create an image pack for the pet: the seven state GIFs (idle, busy, attention, celebrate,
    dizzy, sleep, heart; 96x100 on black) from ONE picture of a front-facing character at
    `image_path` (absolute path; transparent PNG best). Without an image, `prompt` describes the
    character and Codex image_gen draws it first (2-4 minutes)."""
    body: dict = {"name": name}
    if image_path:
        body["imagePath"] = image_path
    if prompt:
        body["prompt"] = prompt
    return _run("/api/packs/create", body, 420)


@mcp.tool()
def studio_auto_sprite(name: str, image: str | None = None, image_path: str | None = None, prompt: str | None = None,
                       moves: dict | None = None, canvas: str | None = None, send: bool = False, pet: str | None = None,
                       repairs: int = 2) -> dict:
    """AutoSprite: ONE picture in, the pet's seven states out, every pose REDRAWN by an image model
    (not the puppet bends of studio_create_pack). Codex image_gen draws the character in 14 poses as
    one sheet, the sheet is cut into frames, then the AI checks its own frames against the picture
    and redraws the bad states (up to `repairs` rounds). 4-10 minutes.
    The picture: `image` (a studio image name, see /api/images), `image_path` (absolute path), or
    `prompt` (Codex draws the character first). `moves`: custom poses per state, e.g.
    {"busy": ["stirring a pot", "tasting from the spoon"]}. `canvas`: also place every frame on that
    canvas so it can be touched up. `send`: put the pack on the pet (`pet` e.g. "B018").
    Returns the pack, the sheet and contact-sheet URLs, the per-state frame URLs and each review."""
    body: dict = {"name": name, "repairs": repairs, "send": send}
    for k, v in {"image": image, "imagePath": image_path, "prompt": prompt, "moves": moves, "canvas": canvas, "pet": pet}.items():
        if v is not None:
            body[k] = v
    return _run("/api/sprite/auto", body, 1500)


@mcp.tool()
def studio_build_firmware(board: str, pack: str = "siamese") -> dict:
    """Build the pet firmware (ESP-IDF v6) for `board`: jc3248 (3.5in JC3248W535), lcd28 (2.8in
    ILI9341) or sc01 (WT32-SC01 Plus). `pack`: the bundled pack it boots with. First build of a
    board takes several minutes; later ones under a minute."""
    return _run("/api/firmware/build", {"board": board, "pack": pack}, 1200)


@mcp.tool()
def studio_flash_ble(kind: str, name: str | None = None, board: str | None = None, pet: str | None = None) -> dict:
    """Put something on a pet over Bluetooth, through OraclePet. `kind`:
    - "app": send the built wasm app `name` and run it (a few KB, ~1 s)
    - "run": run app `name` already on the pet ("stop" = back to the firmware's own behaviour)
    - "pack": send image pack `name` and show it (~150 KB, ~6 s)
    - "firmware": OTA the built firmware for `board` (~1.4 MB; the pet reboots, with rollback)
    `pet`: the end of the pet's name, e.g. "B018" (SC01 Plus) or "D350"; default the first pet."""
    body = {"kind": kind, "name": name, "board": board, "pet": pet}
    return _run("/api/flash/ble", {k: v for k, v in body.items() if v is not None}, 300)


@mcp.tool()
def studio_flash_usb(board: str, port: str) -> dict:
    """Flash the built firmware for `board` over USB to `port` (/dev/cu.usbmodem…; see
    studio_state): bootloader, partition table, app and every pack. Replaces whatever the board
    runs, so only for a board meant to be a pet."""
    return _run("/api/flash/usb", {"board": board, "port": port}, 600)


BLOCKS_DOC = """Blockly JSON (Blockly.serialization.workspaces.save): {"blocks": {"languageVersion": 0,
"blocks": [top blocks with x, y]}, "variables": [{"name": "taps", "id": "taps"}]}. Statement blocks chain with
"next": {"block": {...}}; inputs are "inputs": {"NAME": {"block": {...}}} (or "shadow" for a default).

Event hats (top blocks; statements go in input DO): pet_on_start, pet_on_tap, pet_every (field MS),
pet_on_fleet. Pet: pet_show (field STATE: PET_IDLE|PET_BUSY|PET_ATTENTION|PET_SLEEP), pet_react,
pet_caption / pet_status / pet_say / pet_log (input TEXT), pet_pack (field NAME). Sound: pet_sound (field
KIND: PET_RIBBIT|PET_BLIP_UP|PET_BLIP_DOWN), pet_tone (inputs HZ, MS). Values: pet_millis, pet_tap (field
AXIS x|y), pet_fleet (field WHICH total|running|waiting), pet_join (inputs A, B), text (field TEXT),
math_number (field NUM). Also controls_if (IF0/DO0.., ELSE), logic_compare (OP EQ|NEQ|LT|LTE|GT|GTE, A, B),
logic_operation (OP AND|OR), logic_negate, logic_boolean, controls_repeat_ext (TIMES, DO),
controls_whileUntil, math_arithmetic (OP ADD|MINUS|MULTIPLY|DIVIDE, A, B), math_modulo (DIVIDEND, DIVISOR),
math_random_int (FROM, TO), variables_get / variables_set (field VAR {"id"}, input VALUE), math_change
(VAR, DELTA). Numbers are ints. Blocks outside a hat do nothing."""


@mcp.tool()
def studio_get_blocks() -> dict:
    """The blocks program in the page right now (Blockly JSON), its name, and the C it makes.
    Whatever a person has built in the Blocks tab, live."""
    _ensure_server()
    l = _req("/api/live")
    return {"name": l["name"], "rev": l["rev"], "pages_open": l["pages"], "blocks": l["blocks"], "c": l["c"]}


def studio_set_blocks(blocks: dict, name: str = "blocks", build: bool = True) -> dict:
    _ensure_server()
    r = _req("/api/live/blocks", {"name": name, "blocks": blocks})
    out: dict = {"rev": r["rev"], "c": r["c"]}
    if build:
        out["build"] = _run("/api/blocks/build", {"name": name}, 180)
    return out


studio_set_blocks.__doc__ = """Replace the blocks program: it appears in every open page at once (Blocks tab). With
`build` it is compiled to wasm and the page runs it in its simulator. Returns the C, and the build.

""" + BLOCKS_DOC
mcp.tool()(studio_set_blocks)


@mcp.tool()
def studio_get_code() -> dict:
    """The app code in the page's Code tab right now: name, lang, source."""
    _ensure_server()
    return _req("/api/live").get("code") or {"error": "the Code tab has not sent anything yet"}


@mcp.tool()
def studio_set_code(source: str, name: str = "studio-hello", lang: str = "c", build: bool = True) -> dict:
    """Put code in the page's Code tab (live), and with `build` compile it and run it in the page's
    simulator. lang: c, zig, rust or as. See studio_build_app for the API."""
    _ensure_server()
    _req("/api/live/code", {"name": name, "lang": lang, "source": source})
    if not build:
        return {"ok": True}
    r = _run("/api/apps/build", {"name": name, "source": source, "lang": lang}, 180)
    if r.get("status") == "ok":
        try:
            _req("/api/live/command", {"type": "simulate", "name": name})
        except RuntimeError as e:
            r["simulate"] = str(e)
    return r


@mcp.tool()
def studio_simulate(name: str, pack: str | None = None) -> str:
    """Run built app `name` in the page's simulator (optionally on animation pack `pack`)."""
    _ensure_server()
    body = {"type": "simulate", "name": name}
    if pack:
        body["pack"] = pack
    return json.dumps(_req("/api/live/command", body))


@mcp.tool()
def studio_tap(x: int = 160, y: int = 200) -> list:
    """Tap the simulated pet screen at (x, y) in pet pixels (320 x 480), then show the screen."""
    _ensure_server()
    _req("/api/live/command", {"type": "tap", "x": x, "y": y})
    time.sleep(1.2)
    return studio_screen()


@mcp.tool()
def studio_screen() -> list:
    """See the simulator: a picture of the simulated pet screen (320 x 480, as the pet draws it),
    plus its state (app, pack, animation, caption, status line, recent log)."""
    _ensure_server()
    l = _req("/api/live")
    info = {"sim": l.get("sim"), "screen_age_s": round(time.time() - l["screenAt"] / 1000, 1) if l.get("screenAt") else None,
            "pages_open": l["pages"]}
    try:
        with urllib.request.urlopen(BASE + "/api/live/screen.png", timeout=5) as r:
            return [Image(data=r.read(), format="png"), json.dumps(info)]
    except urllib.error.HTTPError:
        return [json.dumps({**info, "error": "no screen yet: open the page, run an app in the simulator"})]


@mcp.tool()
def studio_show_tab(tab: str) -> str:
    """Switch the open page to a tab: Blocks, Code, Image, Firmware or Jobs."""
    _ensure_server()
    return json.dumps(_req("/api/live/command", {"type": "tab", "tab": tab}))


# ---- studio v2: the designer (http://127.0.0.1:4810/v2) ----
# Every action a person has in the designer, for the agent. The call goes to the designer page that
# was focused last and runs there, so a person watching sees each change. Coordinates are artboard
# pixels, 384 x 400 (the pet's 96 x 100 frame at 4x); colours are CSS ("#f2994a", "tomato").

# Which canvas this agent works on and who it is: canvas_use() for the session, or the environment
# (PET_STUDIO_CANVAS, PET_STUDIO_AGENT). Each agent runs its own MCP server process, so Claude can
# draw on "fox" while Codex draws on "dragon", or both on one canvas; canvas_since shows who did what.
SESSION = {"canvas": os.environ.get("PET_STUDIO_CANVAS", "main"), "by": os.environ.get("PET_STUDIO_AGENT", "claude")}


def _call(action: str, args: dict | None = None, timeout_s: float = 30) -> dict:
    _ensure_server()
    body = {"action": action, "args": {k: v for k, v in (args or {}).items() if v is not None}, "timeoutMs": int(timeout_s * 1000),
            "canvas": SESSION["canvas"], "by": SESSION["by"]}
    return _req("/api/live/call", body, timeout=timeout_s + 5)["result"]


@mcp.tool()
def design_view() -> list:
    """See the designer: a picture of the current frame plus its state (which pet state and frame,
    frames drawn per state, every layer with position/size/colour, tool, colour, last pack)."""
    r = _call("view")
    png = r.pop("png", None)
    out: list = [json.dumps(r)]
    if png:
        import base64
        out.insert(0, Image(data=base64.b64decode(png.split(",", 1)[1]), format="png"))
    return out


@mcp.tool()
def design_goto(state: str, frame: int = 1) -> dict:
    """Open a frame of a pet state: idle, busy, attention, celebrate, dizzy, sleep, heart. Frame 1 of
    idle is the base every empty state is made from; a frame number past the end adds empty frames."""
    return _call("goto", {"state": state, "frame": frame})


@mcp.tool()
def design_frame(op: str) -> dict:
    """Frames of the current state: "add" (empty frame after this one), "duplicate", "delete"."""
    return _call("frame", {"op": op})


@mcp.tool()
def design_stroke(points: list[list[float]], color: str | None = None, size: float | None = None, erase: bool = False) -> dict:
    """A brush stroke through `points` [[x, y], ...]; with `erase` it rubs out instead."""
    return _call("stroke", {"points": points, "color": color, "size": size, "erase": erase})


@mcp.tool()
def design_shape(kind: str = "rect", x: float = 100, y: float = 100, w: float = 120, h: float = 80,
                 color: str | None = None, opacity: float = 1, radius: float = 6) -> dict:
    """A filled rectangle ("rect", rounded by `radius`) or "ellipse" with its box at x, y, w, h."""
    return _call("shape", {"kind": kind, "x": x, "y": y, "w": w, "h": h, "color": color, "opacity": opacity, "radius": radius})


@mcp.tool()
def design_text(text: str, x: float = 40, y: float = 40, size: float = 48, color: str | None = None) -> dict:
    """A text layer (bold) at x, y; `size` in artboard pixels."""
    return _call("text", {"text": text, "x": x, "y": y, "size": size, "color": color})


@mcp.tool()
def design_image(path: str | None = None, url: str | None = None, prompt: str | None = None, x: float | None = None,
                 y: float | None = None, width: float | None = None, remove_background: bool = False) -> dict:
    """Place a picture as a layer: a file on this Mac (`path`), a `url`, or a `prompt` that Codex
    draws first (2-4 minutes). Fitted and centred unless x / y / width are given;
    `remove_background` cuts out a plain background."""
    return _call("image", {"path": path, "url": url, "prompt": prompt, "x": x, "y": y, "width": width,
                           "remove_background": remove_background}, timeout_s=420 if prompt else 60)


@mcp.tool()
def design_svg(svg: str | None = None, path: str | None = None, x: float | None = None, y: float | None = None,
               width: float | None = None, split: bool = False, name: str | None = None) -> list:
    """Place vector art: SVG markup (`svg`) or an .svg file (`path`). It stays vector: paths,
    shapes and text become objects you can move, scale and recolour; one group by default, or with
    `split` one layer per element. Fitted and centred unless x / y / width are given. Write SVG with a
    viewBox; the artboard is 384 x 400 (the pet frame at 4x, shown on black)."""
    return _call("svg", {"svg": svg, "path": path, "x": x, "y": y, "width": width, "split": split, "name": name})


@mcp.tool()
def design_layer(name: str, op: str = "update", props: dict | None = None) -> dict:
    """Change a layer (by its name from design_view, e.g. "stroke 1", or its start). op: update
    (props: x, y, width, height, angle, opacity, color, visible), select, up, down, top, bottom,
    delete, show, hide, lock, unlock, remove_background."""
    return _call("layer", {"name": name, "op": op, "props": props or {}})


@mcp.tool()
def design_edit(action: str) -> dict:
    """Edit the current frame: "undo", "redo" or "clear" (removes every layer)."""
    if action not in ("undo", "redo", "clear"):
        raise ValueError("action: undo, redo or clear")
    return _call(action)


@mcp.tool()
def design_tool(tool: str | None = None, color: str | None = None, size: float | None = None,
                zoom: float | None = None, onion: bool | None = None) -> dict:
    """The person's tool settings: tool (select, brush, eraser, rect, ellipse, text), colour, brush
    size, zoom (0.75-2.5) and onion skin."""
    return _call("tool", {"tool": tool, "color": color, "size": size, "zoom": zoom, "onion": onion})


@mcp.tool()
def design_create_sprite(name: str, fps: int = 8) -> dict:
    """Create the sprite pack: idle frame 1 is the base for every state left empty; each state with
    frames of its own plays them at `fps`. Returns the pack's GIFs (96 x 100)."""
    return _call("create_sprite", {"name": name, "fps": fps}, timeout_s=180)


@mcp.tool()
def design_send_to_pet(name: str | None = None, pet: str | None = None) -> dict:
    """Send a pack (default: the one just created) to a pet over BLE and show it; `pet` is the end
    of its name ("B018"), default the first connected pet."""
    return _call("send_to_pet", {"name": name, "pet": pet}, timeout_s=240)


# ---- canvas_*: the designer page the droidread way (see, find, tap, drag, type, key, since) ----
# Cheap reads first: canvas_focus (what is open), canvas_snapshot (the tree with [ref=eN] / [ref=lN]
# handles: the one you act on), canvas_query (find), canvas_screenshot (the artboard picture).
# Then act like a person: canvas_tap / canvas_drag go through the current tool (the brush draws,
# select moves, rect sizes), canvas_type / canvas_key, and canvas_since reads every change after a
# cursor, marked "person" or "agent", so the agent can follow what a designer does by hand.

def _png_out(png: str | None, info: dict | None = None) -> list:
    import base64
    out: list = []
    if png:
        out.append(Image(data=base64.b64decode(png.split(",", 1)[1]), format="png"))
    if info is not None:
        out.append(json.dumps(info))
    return out


@mcp.tool()
def canvas_use(canvas: str, agent: str | None = None) -> dict:
    """Work on canvas `canvas` (a-z 0-9 - _) from now on in this session, and sign changes as
    `agent` (e.g. "codex", "omx", "claude"). A person opens it at http://127.0.0.1:4810/v2?canvas=<id>
    and sees every change live; canvas_since lists them by agent."""
    if not re.fullmatch(r"[a-z0-9_-]{1,32}", canvas):
        raise ValueError("canvas: a-z 0-9 - _, at most 32")
    SESSION["canvas"] = canvas
    if agent:
        SESSION["by"] = agent[:24]
    _ensure_server()
    c = _req("/api/canvases")
    return {**SESSION, "open_in_browser": canvas in c["open"], "url": f"{BASE}/v2?canvas={canvas}",
            "hint": None if canvas in c["open"] else "ask the person to open the url (calls fail until a page shows it)"}


@mcp.tool()
def canvas_list() -> dict:
    """Canvases open in a browser now, and canvases saved on the server; plus this session's canvas."""
    _ensure_server()
    return {**_req("/api/canvases"), "session": SESSION}


@mcp.tool()
def canvas_where() -> dict:
    """Is a designer page open and reachable (the server, pages on the live link, OraclePet)."""
    _ensure_server()
    l = _req("/api/live")
    s = _req("/api/state")
    return {"server": BASE, "pages_open": l["pages"], "designer": f"{BASE}/v2",
            "oraclePet": s["oraclePet"], "pets": [f"{p['name']}: {p['link']}" for p in s["pets"]]}


@mcp.tool()
def canvas_focus() -> dict:
    """What the designer has open, instantly: state, frame, tool, colour, selection, layer count,
    last pack and job, and the change cursor for canvas_since. Start here."""
    return _call("focus")


@mcp.tool()
def canvas_snapshot(grep: str | None = None) -> str:
    """The page as a tree, one line per control or artboard object, each with a handle: [ref=eN]
    for page controls (tools, state chips, frames, layer rows, buttons, inputs) with their CSS box,
    [ref=lN] for objects on the artboard (art:path, art:image, art:i-text...) with their artboard box
    (384 x 400). `grep` filters lines (a regex); refs still come from the whole tree. Refs change
    when the page does: snapshot again after acting."""
    r = _call("snapshot", {"grep": grep})
    return f"{r['note']}\n{r['tree']}\n({r['count']} items)"


@mcp.tool()
def canvas_query(text: str | None = None, textContains: str | None = None, role: str | None = None) -> list:
    """Find controls or artboard objects by exactly one of: text (exact name), textContains, role
    (button, input:range, layer-row, art:image, art:path...). Returns refs to tap."""
    return _call("query", {"text": text, "textContains": textContains, "role": role})


@mcp.tool()
def canvas_screenshot(width: int = 384) -> list:
    """The artboard as a picture (transparent where nothing is drawn), `width` px wide (96 = the
    pet's own size)."""
    return _png_out(_call("screenshot", {"width": width})["png"])


@mcp.tool()
def canvas_tap(ref: str | None = None, text: str | None = None, textContains: str | None = None,
               x: float | None = None, y: float | None = None) -> dict:
    """Tap like a person: a `ref` from canvas_snapshot (preferred), a control by text, or a point
    x, y on the artboard, where the current tool acts (select picks the object there, brush makes
    a dot, rect / ellipse a default shape, text a text layer). Refuses on 0 or 2+ matches."""
    return _call("tap", {"ref": ref, "text": text, "textContains": textContains, "x": x, "y": y})


@mcp.tool()
def canvas_drag(points: list[list[float]], durationMs: int = 300) -> dict:
    """A real pointer drag on the artboard through `points` [[x, y], ...]: with the brush it draws,
    the eraser rubs out, select moves what is under the first point, rect / ellipse size a shape.
    Pick the tool first (canvas_key "b", "v", "r"... or canvas_tap the tool)."""
    return _call("drag", {"points": points, "durationMs": durationMs})


@mcp.tool()
def canvas_type(text: str, ref: str | None = None) -> dict:
    """Type into an input or textarea (pack name, prompt, fps...) or set a text layer's words;
    `ref` from canvas_snapshot, default what has focus or the selected layer."""
    return _call("type", {"text": text, "ref": ref})


@mcp.tool()
def canvas_key(key: str, meta: bool = False, shift: bool = False) -> dict:
    """Press a key as a person: tool shortcuts v b e r o t, Delete / Backspace (remove the
    selection), Escape; `meta` for Cmd (Cmd-Z undo, with `shift` redo)."""
    return _call("key", {"key": key, "meta": meta, "shift": shift})


@mcp.tool()
def canvas_since(cursor: int = 0, limit: int = 100) -> dict:
    """Every change on this session's canvas after `cursor` (layers added / changed / removed,
    frames opened, tools picked, sprites created), each signed "person" or the agent's name
    (claude, codex, omx...). Kept by the server, so it survives reloads and works with no page open. Pass the returned cursor next time to read
    only what is new: how the agent follows a designer working by hand."""
    _ensure_server()
    return _req(f"/api/canvas/{SESSION['canvas']}/since?cursor={int(cursor)}&limit={int(limit)}")


@mcp.tool()
def studio_flasher(board: str, pack: str, apps: list[str] | None = None, autorun: str | None = None,
                   packs: list[str] | None = None) -> dict:
    """Prepare a web-flasher bundle: firmware for `board` (jc3248, lcd28, sc01) that boots as `pack`,
    a storage image holding that pack plus any extra `packs`, and `apps` (built wasm apps, by name),
    and an esp-web-tools page. `autorun` (one of apps; default the only one) starts by itself on
    the pet's first boot. Anyone opens the returned url in Chrome or Edge, plugs the pet in by USB
    and installs. Also a .zip to hand out."""
    body: dict = {"board": board, "pack": pack, "apps": apps or [], "packs": packs or []}
    if autorun:
        body["autorun"] = autorun
    r = _run("/api/flasher/stage", body, 1200)
    if r.get("status") == "ok":
        r["result"]["open"] = BASE + r["result"]["url"]
    return r


@mcp.tool()
def studio_job(job_id: str) -> dict:
    """A job's status, result and the end of its log (for a job a tool returned while still running)."""
    _ensure_server()
    j = _req(f"/api/jobs/{job_id}")
    j["log"] = j.get("log", [])[-25:]
    return j


if __name__ == "__main__":
    mcp.run()
