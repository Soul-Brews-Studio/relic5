# pet-studio — make things for the desk pet, and put them on it

> **In relic5** (merged 2026-10-24 from esp32-oracle `lab/pet-studio` @ 97f6280, Nat: "merge all"). It runs on the
> Mac that holds the pets (Bluetooth goes through OraclePet.app, firmware through ESP-IDF), not on the relic5 hub.
> The pet's own code stays in esp32-oracle's `lab/`: `pet-sdk`, `jc3248-pet-idf`, `desk-pet-mac`. The server finds
> that lab through `PET_LAB`, else `$(ghq root)/github.com/Soul-Brews-Studio/esp32-oracle/lab`. Until esp32-oracle
> PR #28 merges, the lab is on its branch, so set
> `PET_LAB=$(ghq root)/github.com/Soul-Brews-Studio/esp32-oracle/wt/siamese-pack-esp32-21oct-wed2026/lab`.
>
> `just pet-studio` (relic5 root) installs, builds the page and starts the server on http://127.0.0.1:4810.
> Each oracle's page in the hub (Oracles tab) has a **Pet** prompt: give it to `studio_auto_sprite`, then keep the
> pack's GIFs on the oracle's page with relic5's `relic_artifact_put`.

One local server, a web page and an MCP server, over the tools this lab already has:

| make | how | goes to the pet |
|---|---|---|
| an app **in blocks** | Blockly blocks for the pet API (like KBIDE / DBK Screen), C generated live beside them (`shared/petblocks.ts`), then the same path as code | same as an app |
| an **app** | C, Zig, Rust or AssemblyScript → `.wasm` with [`../pet-sdk`](../pet-sdk/README.md), load-checked in the pet's own WAMR, then run in the page's simulator | BLE partial update, a few KB, ~1 s |
| an **image pack** | one picture → the seven state GIFs (`tools/make-pack.sh`); no picture: Codex `image_gen` draws one from a prompt | BLE partial update, ~150 KB, ~6 s |
| an **AI sprite** | one picture → every state's poses REDRAWN by Codex `image_gen`, checked and repaired by the AI itself (AutoSprite, below) | same as an image pack |
| **firmware** | ESP-IDF v6 build of [`../jc3248-pet-idf`](../jc3248-pet-idf) for `jc3248`, `lcd28` or `sc01` | BLE OTA (with rollback), or USB |

```
 web page (Vite + React + Blockly) ─┐   ◄── SSE: the agent's blocks, code, taps
                                    ├─► server/index.ts  (Bun, 127.0.0.1:4810) ─► pet-sdk/build.sh, make-pack.sh, idf.py
 MCP (petstudio_mcp.py)  ───────────┘                                         └─► OraclePet.app (deskpet:// URLs) ─► BLE ─► pets
```

BLE goes through OraclePet (`../desk-pet-mac`): it holds the pets' Bluetooth links and macOS
denies Bluetooth to a bare process an agent starts. The server opens `deskpet://` URLs and follows
`/tmp/deskpet-status.json` until the transfer ends.

## Studio v2: the Designer (http://127.0.0.1:4810/v2)

A designer's canvas for the pet's sprite, no blocks: draw, paste or generate pictures into a frame,
stack them as layers, give a state frames of its own, then **Create sprite** makes the pack and
**Send to pet** puts it on the pet over BLE.

- Artboard 384 x 400: the pet's 96 x 100 frame at 4x, scaled down by the server.
- Tools: select/move (V), brush (B), eraser (E), rectangle (R), ellipse (O), text (T), place an image
  (button, Cmd-V paste, or drop), colour (recolours the selection too), undo / redo (Cmd-Z), delete.
- Layers: order, show/hide, lock, opacity, and ✂ Remove background for a picture on a plain background.
- Generate a picture: Codex `image_gen` draws it (2-4 min), background cut out, placed as a layer.
- Frames per state (idle, busy, attention, celebrate, dizzy, sleep, heart) along the bottom:
  add, duplicate, delete, onion skin, play at N fps.
- Create sprite: idle frame 1 is the base. Every state without frames of its own is made from it by
  `tools/make-pack.sh`'s moves; each state you drew plays your frames. Server: `POST /api/sprite/create`.

Every action is an MCP tool too. The call goes to the designer page focused last, so a person
watching sees each change (`POST /api/live/call` → SSE → the page runs it → `/api/live/result`):

| MCP tool | does |
|---|---|
| `design_view` | a picture of the current frame plus state, frames per state and every layer |
| `design_goto(state, frame)` | open a state's frame (a number past the end adds frames) |
| `design_frame(op)` | add, duplicate, delete a frame |
| `design_stroke(points, color, size, erase)` | a brush stroke, or rub out |
| `design_shape(kind, x, y, w, h, color, opacity, radius)` | rectangle or ellipse |
| `design_text(text, x, y, size, color)` | a text layer |
| `design_image(path \| url \| prompt, x, y, width, remove_background)` | place a picture, or have Codex draw one |
| `design_layer(name, op, props)` | update (x, y, width, height, angle, opacity, color), select, up/down/top/bottom, delete, show/hide, lock/unlock, remove_background |
| `design_edit(action)` | undo, redo, clear |
| `design_tool(tool, color, size, zoom, onion)` | the person's tool settings |
| `design_create_sprite(name, fps)` | make the pack |
| `design_send_to_pet(name, pet)` | send it over BLE and show it |

Checked 2026-10-21 over MCP: the fox placed from a file with its background cut out, a stroke, a
tilted "MCP" text, two hand-drawn heart frames, create sprite (heart from the 2 frames, the rest from
the base, 100 KB), then sent: "Pet now shows mcp-design" on Claude-B018.

## AutoSprite: one picture, every pose redrawn by the AI

What [AutoSprite](https://www.autosprite.io) does for game sheets (nexus-oracle#130, from a reel by
Sarafim Seraphim), done the studio's way, with no person in the loop:

1. **Sheet.** Codex `image_gen` gets the one picture and draws the same character in 14 poses as
   ONE 4x4 sheet: two frames each of idle (blink), busy (typing), attention (wave), celebrate
   (jump, land), dizzy (spiral eyes), sleep (curled up), heart (hug, hold up). One image keeps the
   character the same from pose to pose.
2. **Slice.** `tools/slice-sheet.py` keys out each cell's background, keeps the biggest blob (plus
   nearby parts such as a heart or a laptop), scales every frame by ONE factor so sizes stay true,
   and stands each on the artboard's floor. `contact.png` shows the 14 frames as the pet will.
3. **Check and repair.** Codex looks at the picture beside the contact sheet and names the states
   that are off (wrong character, wrong pose, cut off). Those are drawn again, each state as a
   2-frame strip in parallel, with the idle frame as a second reference. Up to `repairs` rounds.
4. **Pack, canvas, pet.** The GIFs come from the redrawn frames (`packFromFrames`, the same code
   path as "Make the sprite"); with `canvas` the frames land in that canvas's states so a person or
   an agent can touch them up; with `send` the pack goes to the pet.

| from | how |
|---|---|
| Designer | "AI makes the whole sprite": idle frame 1 is the picture |
| MCP | `studio_auto_sprite(name, image \| image_path \| prompt, moves, canvas, send, pet)` |
| shell | `bun tools/canvas.ts <canvas> auto_sprite '{"name": "fox", "path": "/tmp/fox.png", "send": true}'` |
| HTTP | `POST /api/sprite/auto` |

`moves` sets a state's two poses for this character, e.g. `{"busy": ["stirring a pot", "tasting
from the spoon"]}`. Measured 2026-10-22 on the fox picture: sheet 2 min 44 s, a 2-frame repair
strip 1 min 12 s. Agents get `tools/agent-brief-auto.md`: make the picture, run it, judge it like an
art director, ship it.

## Many agents, named canvases

A canvas is a named design: `/v2?canvas=<id>`, saved on the server (`workspace/canvases/<id>.json`).
Every call names its canvas and is signed by its agent, so Claude, Codex, omx or thclaws can each draw
on their own canvas (or share one) while a person watches; `canvas_since` lists every change by who
made it, from a log the server keeps (`<id>.log.jsonl`), so it works with no page open. A call to a
canvas no page shows opens one in ego-browser's own "Pet Studio canvases" space.

- MCP: `canvas_use(canvas, agent)` for the session (or `PET_STUDIO_CANVAS`, `PET_STUDIO_AGENT`),
  `canvas_list`, then any `design_*` / `canvas_*` tool. Codex has the server in `~/.codex/config.toml`
  (tools pre-approved, signing as "codex").
- Shell, for any agent: `PET_STUDIO_AGENT=omx bun tools/canvas.ts <canvas> <action> '<json>'`
  (`- list`, `since`, `screenshot > f.png`, every design action).
- `design_svg` places SVG (markup or a file) as vector layers, grouped or split.

`tools/agent-brief.md` is one full prompt that takes an agent from nothing to its character on the pet
(draw on its canvas, frames for busy / heart / sleep, make the sprite, send it). Three rounds on
2026-10-21, single shot each:

| agent | result |
|---|---|
| `omx exec` | pink axolotl, squash-and-stretch bounce, rising heart: "Pet now shows omx-axolotl · 115 KB in 9 s" |
| `claude -p` | blue robot; brief v2 added squash-and-stretch, feet and a 96 px check: "Pet now shows claude-robot2" |
| `thclaws -p -m zai/glm-5.2` | tabby cat with a bell collar, ~13 min: "Pet now shows thclaws-cat · 129 KB" |

Each round's misses became the next brief (SVG through a file, a safe box so nothing is cut off,
the heart clear of the head, a hand-drawn sleep, never strip states to make a pack fit). Round 3, on
brief v4, all three single shot and all on the pet: claude-robot3 (86 KB in 6 s), omx-axolotl3
(126 KB in 8 s), thclaws-cat3 (95 KB in 8 s), each with hand-drawn sleep, a squash-and-stretch
bounce and the heart clear of the head.

## On the pet: over BLE, or a web-flasher bundle

| what | format | over BLE (no reboot unless firmware) | baked into a flash |
|---|---|---|---|
| a character pack | 7 GIFs + manifest | partial update, ~100 KB in ~8 s | `storage.bin` |
| an app (blocks or code) | wasm | partial update, ~4 KB in ~1 s | `storage.bin` `apps/`, optional autorun |
| firmware | ESP32 `.bin` | full OTA with rollback, ~1.4 MB in ~53 s | the app partition |

"Play the sprite" (On the pet) plays the made pack's seven states in turn before it is sent.

`studio_flasher(board, pack, packs, apps, autorun)` (`POST /api/flasher/stage`) prepares an
esp-web-tools bundle at `/flasher/<board>-<pack>/` (and a `.zip`): firmware that boots as `pack`, a
storage image made like the firmware build makes it (littlefs-python, block 4096, name-max 64) with
just the chosen packs and apps, every offset from the build's `flasher_args.json`, and an install page.
A fresh pet starts the `autorun` app once on its first boot. Checked on the WT32-SC01 Plus: 420 of
3072 KB used; first boot showed omx-axolotl and "first boot: starting the baked-in app 'dice'".

## Blocks, and the live link to Claude Code

The **Blocks** tab is a Blockly workspace with the pet's API as blocks, built like the block editors
in nat-build-with-oracle/KBProIDE (KBIDE, DBK Screen):

| category | blocks |
|---|---|
| Events | when the app starts, when the screen is tapped, every N ms, when the agents change |
| Pet | show idle / busy / attention / sleep, show the heart, caption, status line, switch pack, say, log |
| Sound | ribbit / blip up / blip down, tone Hz for ms |
| Values | time since start, tap x / y, agents total / running / waiting, join text and numbers |
| Canvas | canvas / frame mode, fill, rectangle, circle, line, write text, colour, rgb, screen width / height |
| and Blockly's | if / else, compare, and / or / not, repeat, while, + - × ÷, remainder, random, variables |

Two modes, switched at the top of the tab:

- **Frame mode**: the pet plays its pack's GIF frames; the blocks pick the state, caption and sounds.
- **Canvas mode**: the blocks draw the screen above the HUD themselves (Canvas category: fill,
  rectangle, circle, line, write text, colours, screen size), via `pet_canvas` and the drawing calls
  in `../pet-sdk/pet.h`. It needs pet firmware from 2026-10-21 on. A program that draws starts in
  canvas mode by itself.

The C appears beside the blocks as you build. **Compile** makes the wasm and runs it in the simulator;
**Send to pet** puts it on the pet over BLE. The generator runs headless in the server too, so an
agent's blocks become the same C.

The page and the agent share one live workspace, the way droidcast mirrors a phone. The server keeps
the blocks, the Code tab's source and a picture of the simulator screen; pages receive the agent's
changes over SSE (`/api/live/events`) and send theirs back:

| MCP tool | does, live in the open page |
|---|---|
| `studio_get_blocks` | the blocks a person built (Blockly JSON) and their C |
| `studio_set_blocks(blocks, name, build)` | replace the blocks; with `build`, compile and run them in the simulator |
| `studio_get_code` / `studio_set_code(source, name, lang, build)` | the Code tab, both ways |
| `studio_simulate(name, pack)` | run a built app in the simulator |
| `studio_screen` | a PNG of the simulated screen (320 x 480) plus its state |
| `studio_tap(x, y)` | tap the simulated screen, then show it |
| `studio_show_tab(tab)` | switch the page to Blocks, Code, Image, Firmware or Jobs |

Checked 2026-10-21: an agent wrote a dice program as blocks over MCP; the page showed it, compiled it
(3813 B) and ran it; `studio_screen` showed "tap to roll"; `studio_tap` rolled "dice: 6" with the
heart; a block edited in the page came back through `studio_get_blocks`; then `studio_flash_ble`
ran it on Claude-B018 (WT32-SC01 Plus).

## Run

```bash
bun install
bun run start        # build the page, then serve page + API on http://127.0.0.1:4810
# or, while editing the page:
bun run server       # API on :4810
bun run dev          # Vite on http://127.0.0.1:5174, /api proxied to :4810
```

The MCP server (it starts the API server itself when it is not up):

```bash
claude mcp add petstudio -- uv run --script lab/pet-studio/mcp/petstudio_mcp.py
```

| tool | does |
|---|---|
| `studio_state` | OraclePet and its pets, USB ports, built firmware per board, apps, packs, recent jobs |
| `studio_build_app(name, source, lang)` | compile to wasm; returns size, imports, exports |
| `studio_create_pack(name, image_path \| prompt)` | one picture (or a Codex drawing) → a pack |
| `studio_build_firmware(board, pack)` | `jc3248`, `lcd28` or `sc01` |
| `studio_flash_ble(kind, name, board, pet)` | `app`, `run`, `pack` or `firmware`, to the pet whose name ends in `pet` |
| `studio_flash_usb(board, port)` | full flash over USB |
| `studio_job(id)` | a job that was still running when its tool returned |
| live tools | see *Blocks, and the live link* above |

## API

Slow work is a job: a `POST` returns `{job}`, and `GET /api/jobs/:id` has `status`, `log` and
`result`. One job at a time per lane (IDF builds and USB flashes share one, BLE has its own).

| route | body |
|---|---|
| `GET /api/state` | |
| `POST /api/apps/build` | `{name, lang: c\|zig\|rust\|as, source}` |
| `POST /api/packs/create` | `{name, imagePath}` or `{name, imageBase64, imageExt}` or `{name, prompt}` |
| `POST /api/firmware/build` | `{board, pack}` |
| `POST /api/sprite/auto` | `{name, image \| imagePath \| imageBase64 \| prompt, moves?, repairs?, canvas?, send?, pet?, fps?}`: AutoSprite |
| `POST /api/flash/ble` | `{kind: app\|run\|pack\|firmware, name?, board?, pet?}` |
| `POST /api/flash/usb` | `{board, port}` |
| `POST /api/blocks/build` | `{name, blocks?}`: blocks → C → wasm; the page simulates it |
| `GET /api/live`, `GET /api/live/events` (SSE), `GET /api/live/screen.png` | the shared workspace |
| `POST /api/live/blocks`, `/api/live/code`, `/api/live/command` | `{blocks}`, `{name, lang, source}`, `{type: simulate\|tap\|tab, ...}` |
| `GET /api/apps/<name>.wasm`, `/api/apps/<name>/source`, `/api/packs/<name>/<file>` | |

Files the studio makes live in `workspace/` (git-ignored): app sources, uploaded or drawn images,
and the packs. Built apps land in `../pet-sdk/build/` like any other.

## Needs

macOS, Bun, `uv`, zig (C/Zig apps), ImageMagick + gifsicle (packs), ESP-IDF v6 at `~/esp/esp-idf-v6`
with `~/esp/pyshim` putting python3.13 first (firmware), OraclePet in /Applications (BLE), and the
`codex` CLI only for drawing a picture from a prompt.

The server binds 127.0.0.1 only: it runs builds and flashes boards.

---

🤖 Nexus Oracle (Claude, AI) for Nat · laris-co/nexus-oracle#130
