# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow>=10", "numpy>=1.26", "scipy>=1.11"]
# ///
"""Cut an AI-drawn sprite sheet into pet frames.

    uv run tools/slice-sheet.py <sheet.png> <out-dir> --grid 4x4 --cells idle,idle,busy,busy,...

The sheet is a grid of equal cells on a plain light background (what the auto-sprite prompt asks
image_gen for). For each named cell: key out the background from the cell's edges, keep the
biggest blob (stray bits of a neighbouring cell or a shadow are dropped), and crop it. Every frame
is then scaled by ONE factor, so the character keeps its size from pose to pose (a curled-up sleep
stays smaller than a jump; --fit-to keeps a repaired state as tall as the frame it replaces), and placed bottom-centre on a transparent 384x400 cell, feet on y=372
(the designer's artboard and safe box). Writes <state>-<n>.png, sheet.json (per frame: cell, blob
size, bbox) and contact.png (all frames in a row on black, the way the pet shows them) so an
agent can look at the result before it goes on.
"""
import argparse, json, sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

W, H, FOOT, MAXH = 384, 400, 372, 300


def key(cell: np.ndarray, tol: float) -> np.ndarray:
    """Alpha mask: True where the character is. Background = pixels near the cell's edge colour,
    connected to the edge (so white eyes inside the character survive)."""
    rgb = cell[..., :3].astype(np.int16)
    edge = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    bg = np.median(edge, axis=0)
    near = np.abs(rgb - bg).max(axis=2) <= tol
    if cell.shape[2] == 4:
        near |= cell[..., 3] < 16
    lab, _ = ndimage.label(near)
    border = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    bgmask = np.isin(lab, border[border > 0])
    return ~bgmask


def biggest(mask: np.ndarray) -> np.ndarray:
    lab, n = ndimage.label(mask)
    if n == 0:
        return mask
    sizes = ndimage.sum(mask, lab, range(1, n + 1))
    keep = 1 + int(np.argmax(sizes))
    main = lab == keep
    # keep nearby parts too (a detached heart, a "z", a laptop): blobs at least 3% of the main one
    # whose box touches the main box grown by 15%
    ys, xs = np.where(main)
    y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
    gy, gx = int((y1 - y0) * 0.15), int((x1 - x0) * 0.15)
    out = main.copy()
    for i in range(1, n + 1):
        if i == keep or sizes[i - 1] < sizes[keep - 1] * 0.03:
            continue
        py, px = np.where(lab == i)
        # a part touching the cell's edge is a neighbour's pose spilling over, not ours
        if py.min() == 0 or px.min() == 0 or py.max() == mask.shape[0] - 1 or px.max() == mask.shape[1] - 1:
            continue
        if py.max() >= y0 - gy and py.min() <= y1 + gy and px.max() >= x0 - gx and px.min() <= x1 + gx:
            out |= lab == i
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sheet")
    ap.add_argument("out")
    ap.add_argument("--grid", default="4x4")
    ap.add_argument("--cells", required=True, help="comma list of state names in reading order; '-' skips a cell")
    ap.add_argument("--tol", type=float, default=28)
    ap.add_argument("--fit-to", help="a frame from an earlier slice: scale so the tallest new frame is as tall as it (repairs keep their size)")
    a = ap.parse_args()
    cols, rows = (int(x) for x in a.grid.lower().split("x"))
    names = [c.strip() for c in a.cells.split(",")]
    img = np.array(Image.open(a.sheet).convert("RGBA"))
    sh, sw = img.shape[:2]
    cw, ch = sw / cols, sh / rows
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    crops, info = [], []
    for idx, name in enumerate(names):
        if name in ("-", ""):
            continue
        r, c = divmod(idx, cols)
        if r >= rows:
            break
        cell = img[int(r * ch): int((r + 1) * ch), int(c * cw): int((c + 1) * cw)]
        m = biggest(key(cell, a.tol))
        frac = float(m.mean())
        if frac < 0.01:
            info.append({"cell": idx + 1, "state": name, "empty": True})
            continue
        ys, xs = np.where(m)
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        rgba = cell.copy()
        rgba[..., 3] = np.where(m, rgba[..., 3], 0)
        crops.append((name, Image.fromarray(rgba[y0:y1, x0:x1])))
        info.append({"cell": idx + 1, "state": name, "fill": round(frac, 3), "bbox": [int(x0), int(y0), int(x1), int(y1)],
                     "touches_edge": bool(y0 == 0 or x0 == 0 or y1 == cell.shape[0] or x1 == cell.shape[1])})
    if not crops:
        print("no frames found", file=sys.stderr)
        return 1

    # one scale for every frame: the tallest pose fits MAXH, and nothing gets wider than the safe box
    tallest = max(im.height for _, im in crops)
    target = MAXH
    if a.fit_to and Path(a.fit_to).exists():
        alpha = np.array(Image.open(a.fit_to).convert("RGBA"))[..., 3] > 16
        rows_on = np.where(alpha.any(axis=1))[0]
        if rows_on.size:
            target = int(rows_on.max() - rows_on.min() + 1)
    scale = min(target / tallest, (W - 60) / max(im.width for _, im in crops))
    count: dict[str, int] = {}
    frames = []
    for name, im in crops:
        n = count[name] = count.get(name, 0) + 1
        im = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))), Image.LANCZOS)
        canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        canvas.paste(im, ((W - im.width) // 2, FOOT - im.height), im)
        p = out / f"{name}-{n}.png"
        canvas.save(p)
        frames.append(p)

    contact = Image.new("RGB", (96 * len(frames), 100), "black")
    for i, p in enumerate(frames):
        f = Image.open(p).resize((96, 100), Image.LANCZOS)
        contact.paste(f, (96 * i, 0), f)
    contact.save(out / "contact.png")
    (out / "sheet.json").write_text(json.dumps({"scale": round(scale, 3), "frames": [p.name for p in frames], "cells": info}, indent=1))
    print(json.dumps({"frames": len(frames), "states": count, "scale": round(scale, 3),
                      "edge": [x["cell"] for x in info if x.get("touches_edge")], "empty": [x["cell"] for x in info if x.get("empty")]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
