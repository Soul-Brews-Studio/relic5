# Brief (auto): one picture, the AI makes the whole desk-pet sprite

You are {AGENT}. Work alone, in one go, without asking questions. Your canvas is **{CANVAS}**; a
person is watching it live at http://127.0.0.1:4810/v2?canvas={CANVAS}. Character: **{CHARACTER}**.

The studio can now do what AutoSprite does: from ONE picture of a character, an image model
redraws it in every pose the pet needs (idle, busy, attention, celebrate, dizzy, sleep, heart; two
frames each), checks its own frames against the picture and redraws the bad ones. Your job is to
give it a good picture, judge what comes back like an art director, and ship it to the pet.

## The tool

```bash
S="$(git -C "$(ghq root)/github.com/Soul-Brews-Studio/relic5" rev-parse --show-toplevel)/pet-studio"
export PET_STUDIO_AGENT={AGENT}
bun $S/tools/canvas.ts {CANVAS} <action> '<json args>'
```

| action | args |
|---|---|
| `goto` | `{"state": "idle", "frame": 1}` |
| `clear` | `{}` empties the current frame |
| `svg` | `{"path": "/tmp/{CANVAS}/char.svg", "x": 62, "y": 70, "width": 260}`: vector art (viewBox 0 0 384 400) |
| `image` | `{"prompt": "...", "x": 0, "y": 0, "width": 384}`: Codex draws a picture into the frame (2-4 min) |
| `screenshot` | `{"width": 384}` with `> file.png`: look at it |
| `auto_sprite` | `{"name": "{PACK}", "path": "/tmp/{CANVAS}/ref.png", "moves": {...}, "send": false}`: the AI sprite job (4-10 min). Progress on stderr; the JSON result on stdout has `contact` (all 14 frames in a row on black, as the pet shows them), `sheet`, `frames`, `reviews` |
| `create_sprite` | `{"name": "{PACK}", "fps": 6}`: rebuild the pack from the canvas frames after you touched them up |
| `send_to_pet` | `{"name": "{PACK}", "pet": "{PET}"}` |

URLs in results are on http://127.0.0.1:4810 (e.g. `curl -s http://127.0.0.1:4810<contact> > /tmp/{CANVAS}/contact.png`).

## Do this

1. Make the one picture: a cute, bold, front-facing, full-body character with a clear silhouette
   and bright colours (the pet shows it 96 px tall on black). Either draw it as SVG on idle frame 1,
   or ask `image` with a prompt. Screenshot idle frame 1 (`"width": 384`) to /tmp/{CANVAS}/ref.png
   and look at it. That PNG is the reference for everything.
2. Pick poses that fit THIS character (optional): `moves` overrides the two poses of any state,
   e.g. a chef's busy = `["stirring a pot", "tasting from the spoon"]`.
3. Run `auto_sprite` with `"path": "/tmp/{CANVAS}/ref.png"`. It also fills your canvas's frames.
4. Download `contact` and `sheet` and LOOK at them. Is it the same character in every frame? Does
   each pose read at 96 px? Anything cut off? If one state is weak, fix it on the canvas (goto that
   state's frame, adjust with `layer`, or redraw) and then `create_sprite`; if most is wrong, run
   `auto_sprite` once more with better `moves` or a clearer picture.
5. `send_to_pet` with name `{PACK}` and pet `{PET}`. If the pet refuses, report it and stop.
6. Finish with three lines: the character and poses you chose, what the pet now shows, and one
   thing the auto sprite got wrong or right that surprised you.

Rules: only the canvas tool, curl to the studio, and files under /tmp/{CANVAS}/; never edit the
studio's code; read error messages and adapt.
