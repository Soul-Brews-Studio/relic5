# Brief: design a desk-pet character on a Pet Studio canvas, then put it on the pet

You are {AGENT}. Work alone, in one go, without asking questions. Your canvas is **{CANVAS}**; a
person is watching it live at http://127.0.0.1:4810/v2?canvas={CANVAS}. Character to make:
**{CHARACTER}**.

## The tool

Every action is one shell command (run from any directory):

```bash
S="$(git -C "$(ghq root)/github.com/Soul-Brews-Studio/relic5" rev-parse --show-toplevel)/pet-studio"
export PET_STUDIO_AGENT={AGENT}
bun $S/tools/canvas.ts {CANVAS} <action> '<json args>'
```

The artboard is 384 x 400 px (the pet's 96 x 100 screen at 4x; the pet shows it on black, so dark
colours vanish: use bright, saturated fills and a light outline). Colours are CSS strings.

| action | args |
|---|---|
| `goto` | `{"state": "idle", "frame": 1}`: states idle, busy, attention, celebrate, dizzy, sleep, heart; a frame past the end adds one |
| `clear` | `{}`: empties the current frame |
| `shape` | `{"kind": "ellipse" or "rect", "x", "y", "w", "h", "color", "opacity", "radius"}` (box top-left x, y) |
| `stroke` | `{"points": [[x, y], ...], "color", "size"}` a brush line through the points |
| `text` | `{"text", "x", "y", "size", "color"}` |
| `svg` | `{"path": "/tmp/{CANVAS}/char.svg", "x", "y", "width", "split": false}` (or `"svg": "<svg ...>"` inline): vector art, the best way to draw a whole character at once. Write the SVG to a file first: quoting markup inside JSON in a shell breaks easily |
| `layer` | `{"name": "<layer name>", "op": "update", "props": {"x", "y", "width", "height", "angle", "opacity", "color"}}`, or op `delete`, `up`, `down` |
| `view` | `{}`: JSON of every layer; with `> file.png` you get the picture |
| `screenshot` | `{"width": 384}` with `> file.png`: look at it before moving on |
| `create_sprite` | `{"name": "<pack name>", "fps": 6}`: makes the seven 96 x 100 GIFs |
| `send_to_pet` | `{"name": "<pack name>"}`: puts the pack on the pet over Bluetooth and shows it |

## Do this

1. Write the character as one SVG file (viewBox 0 0 384 400): a clean, cute, bold-shaped character
   with a readable silhouette (head, body, limbs or the creature's own parts), a light 4-6 px
   outline, bright fills. Keep it in /tmp/{CANVAS}/ (your only scratch place).
2. `goto` idle frame 1, `clear`, place it with `svg` (`"x": 62, "y": 70, "width": 260`): centred,
   about 260 px tall, standing on y = 360. The whole character (ears, tail, feet) must stay inside the
   safe box x 30-354, y 30-372: anything outside is cut off on the pet. This frame is the base every
   state you leave empty is made from.
3. `screenshot` with `"width": 96` (the pet's real size) and with `"width": 384`, and look at both.
   Check: feet and every edge visible (nothing cut off), face readable at 96 px, colours bright on
   black. Fix, then screenshot again.
4. Give **busy** two frames that bounce with squash and stretch: frame 1 squashed (wider, shorter,
   lower), frame 2 stretched (narrower, taller, higher); use `layer` update on the placed svg
   (`width`, `height`, `y`). Give **heart** two frames: the character with a red heart above it,
   the heart higher and bigger in frame 2, always clear of the head (no overlap with ears or hair).
   Each new frame starts empty: place the same SVG file again.
   Give **sleep** two frames of your own too: eyes closed (curved lines), the body lower and rounder
   as if curled up, a small "z" beside the head that rises in frame 2.
5. Screenshot every frame you drew (`goto` it first) and check it before going on.
6. `create_sprite` with name `{PACK}` and fps 6.
7. `send_to_pet` with name `{PACK}`. If the pet refuses (for example "storage full"), report it
   and stop: never strip states or flatten frames to make the pack fit.
8. Finish with three lines: what you drew, what the pet now shows (the send result), and one thing
   you would improve.

Rules: only the canvas tool plus files under /tmp/{CANVAS}/; never edit the studio's code; if a
command fails, read its message and adapt. Look at your screenshots: reading a PNG is how you see.
