# Design: Pet Studio Designer (/v2)

Recorded from the built page (web/src/v2/Designer.tsx, web/src/v2/v2.css) on 2026-10-21. Written
in-thread, not by impeccable's documenter subagent (Nat prefers no subagents for hands-on work).

## World: a kiss-cut sticker sheet

The page is the sheet a character gets printed on. The liner is the ground, every panel is a
die-cut sticker lifted off it, and the printer's marks do the work UI chrome usually does.

| role | token | value | use |
|---|---|---|---|
| liner (ground) | `--color-liner` | #e7ebf0 | page; the 24 px printed grid is `--color-liner-ink` #c9d1db |
| sticker | `--color-sticker` | #ffffff | every panel and the artboard |
| key (ink) | `--color-ink` | #16181d | text, the pressed tool, primary dark buttons |
| ink 2 / 3 | `--color-ink-2`, `--color-ink-3` | #4a5160, #6b7383 | secondary (7.9:1), tertiary and labels (4.7:1) on white |
| CutContour | `--color-cut` | #d6006f | selection outlines (dashed), the current state's underline, primary actions, range thumbs, focus |
| cyan | `--color-cyan` | #0087c9 | linked: the connected pet, states that have drawn frames |
| yellow | `--color-yellow` | #ffdd00 | the next step band only, and text selection |
| ok / bad | `--color-ok`, `--color-bad` | #138a52, #c42b1c | job outcomes |

Colour strategy: restrained, neutrals plus process colours as roles. Each colour has one job;
never use magenta or yellow decoratively.

## Material

- Sticker: `rounded-[14px]`, white, a 3 px white bleed ring plus `--shadow-sticker` (offset, soft
  blur). Lifted (the current frame): `--shadow-lift`, `-translate-y-1 -rotate-2`.
- Cut line: 1.5-2 px dashed magenta. Fabric selection uses it too (`borderDashArray [6, 4]`, round
  white handles stroked magenta).
- Registration targets (inline SVG, key ink, 1 px) at the artboard's four corners.
- The artboard: a sticker with a light checkerboard (transparency), 384 x 400 at the zoom.

## Type

Archivo Variable (self-hosted, width axis) for everything. State words 22 px bold lowercase, the
current one stretched to 125 %; panel heads 13 px bold; labels 11 px semibold, +0.02em, 112 %
width, `--color-ink-3`; body 13 px. Numbers `tabular-nums`. No italics, no display face.

## Layout (first viewport, desktop)

1. Header sticker: name + canvas id, the seven states as words, the linked pet, a link to v1.
2. Yellow next-step band: one sentence and its action.
3. Tool strip sticker (left, 60 px): tools, place picture, undo, redo, delete, brush size.
4. The sheet (centre): the artboard sticker with registration marks; below it the swatch bar
   (12 process and pet colours plus any colour), brush, zoom, onion skin.
5. Right column (300 px): On the pet (black 96 x 100 preview), Layers (scrolls at 232 px), Draw me a
   picture (Codex), Sprite (name, make, the seven GIFs, send).
6. Frame strip sticker (bottom): the state's frames as small stickers, add, duplicate, delete,
   playback and fps.

Below `lg` the columns stack, the tools wrap into a row, and the zoom starts at what fits.

## Motion

150 ms ease-out on hover lifts (swatches, frames), button press (`translate-y-px`), progress width
300 ms. No entrance animations. Job running: a pulsing magenta dot.

## Components

- `.btn` (white, liner-ink border), `.btn-cut` (magenta, the one primary per panel), `.tool`
  (`aria-pressed` = key ink fill), `.icon-btn`, `.field`, `.label`. Icons: lucide-react, 1.75 stroke.

## Known exceptions

- The grid background is flagged by impeccable's detector as decorative; it stays because it is the
  liner's printed grid under a canvas tool, the one place the detector allows grids.
