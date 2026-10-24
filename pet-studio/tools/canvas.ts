#!/usr/bin/env bun
// canvas: draw on a Pet Studio canvas from a shell, for agents without the MCP server (Codex, omx,
// scripts). The same actions as the design_* / canvas_* MCP tools, through the same server route.
//
//   bun tools/canvas.ts <canvas> <action> ['{"json": "args"}']
//   PET_STUDIO_AGENT=codex bun tools/canvas.ts fox stroke '{"points": [[40,300],[200,250],[340,300]], "color": "#2e7d32", "size": 12}'
//   bun tools/canvas.ts fox shape '{"kind": "ellipse", "x": 290, "y": 40, "w": 60, "h": 60, "color": "#ffcc00"}'
//   bun tools/canvas.ts fox since '{"cursor": 0}'
//   bun tools/canvas.ts fox screenshot '{"width": 192}' > fox.png      (writes the PNG to stdout)
//   bun tools/canvas.ts - list                                            (canvases open and saved)
//   bun tools/canvas.ts fox auto_sprite '{"name": "fox", "path": "/tmp/fox.png", "send": true}'
//       one picture in, every state redrawn by the AI, checked and repaired by it, frames placed on
//       the canvas, the pack made (and sent): a server job of 4-10 minutes; progress on stderr
//
// Actions: view goto frame stroke shape text image layer clear undo redo tool create_sprite
// send_to_pet focus snapshot query screenshot tap drag type key since auto_sprite. A person watches at
// http://127.0.0.1:4810/v2?canvas=<canvas>; every change is signed with PET_STUDIO_AGENT (default "cli").
const [canvas, action, raw] = process.argv.slice(2);
const base = process.env.PET_STUDIO_URL ?? "http://127.0.0.1:4810";
if (!canvas || !action) {
  console.error("usage: bun tools/canvas.ts <canvas> <action> ['{json args}']   (bun tools/canvas.ts - list)");
  process.exit(2);
}
if (action === "list") {
  console.log(JSON.stringify(await (await fetch(`${base}/api/canvases`)).json(), null, 2));
  process.exit(0);
}
const args = raw ? JSON.parse(raw) : {};
if (action === "since") {                          // the server keeps the log: no page needed
  const q = new URLSearchParams({ cursor: String(args.cursor ?? 0), limit: String(args.limit ?? 100) });
  console.log(JSON.stringify(await (await fetch(`${base}/api/canvas/${canvas}/since?${q}`)).json(), null, 2));
  process.exit(0);
}
if (action === "auto_sprite") {                    // a server job, not a page call
  const body: Record<string, unknown> = { ...args, by: process.env.PET_STUDIO_AGENT ?? "cli" };
  if (canvas !== "-") body.canvas = canvas;
  if (args.path) { body.imagePath = args.path; delete body.path; }
  const s = await (await fetch(`${base}/api/sprite/auto`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) })).json();
  if (s.error) { console.error(s.error); process.exit(1); }
  let seen = 0;
  for (;;) {
    const j = await (await fetch(`${base}/api/jobs/${s.job}`)).json();
    for (const l of j.log.slice(seen)) if (!l.startsWith("$ ")) console.error(l);
    seen = j.log.length;
    if (j.status === "ok") { console.log(JSON.stringify(j.result, null, 2)); process.exit(0); }
    if (j.status === "failed") { console.error(j.error); process.exit(1); }
    await Bun.sleep(2000);
  }
}
const r = await fetch(`${base}/api/live/call`, {
  method: "POST", headers: { "content-type": "application/json" },
  body: JSON.stringify({ canvas, action, args, by: process.env.PET_STUDIO_AGENT ?? "cli", timeoutMs: action === "image" && args.prompt ? 420000 : 60000 }),
});
const d = await r.json();
if (d.error) { console.error(d.error); process.exit(1); }
const png = d.result?.png;
if (png && !process.stdout.isTTY) {                 // screenshot / view piped to a file: the PNG itself
  await Bun.write(Bun.stdout, Buffer.from(String(png).split(",")[1], "base64"));
} else {
  if (png) d.result.png = `(png, ${png.length} chars: pipe to a file to get the image)`;
  console.log(JSON.stringify(d.result, null, 2));
}
