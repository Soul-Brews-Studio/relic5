# Product

<!-- impeccable:product-schema 1 -->

> Written unattended on 2026-10-21: Nat asked for the work to go ahead without questions
> ("go with the best you can… without any ask or wait"). Facts marked *(inferred)* come from the
> brief and the code, not from an interview; correct them freely.

## Platform

web

## Users

- Nat and the people he builds desk pets with: makers, designers and oracle agents in a
  Claude Code session. A designer wants to make the pet's character by hand; an agent drives the
  same page through MCP while a person watches. *(inferred from the requests: "like a photoshop
  for a designer", "all of the actions … have /mcp supports")*
- Used on a Mac, at a desk, beside a physical ESP32 pet on the same table, often with a terminal
  and Claude Code open next to the browser.

## Product Purpose

Pet Studio turns a picture or a drawing into the animated character a desk pet shows: seven
states (idle, busy, attention, celebrate, dizzy, sleep, heart) as 96 x 100 GIFs, then puts it on
the pet over Bluetooth. Success: a person, or an agent, goes from an idea to the character living
on the pet in minutes, without touching a build tool.

## Positioning

The only tool that ends on the device: drawing, frames and states on one canvas, and "Send to
pet" lands on the real ESP32 over BLE through OraclePet. Every action a person has is also an
MCP tool, so an agent designs alongside the person on the same live page.

## Operating Context

- The server runs locally (`bun server/index.ts`, 127.0.0.1:4810); v1 at `/` (blocks, code,
  firmware), the designer at `/v2`.
- OraclePet.app holds the pets' Bluetooth links; the studio asks it with deskpet:// URLs.
- Pets in use: WT32-SC01 Plus (Claude-B018), the 2.8in board (D350), the 3.5in JC3248 (AD48).
- Codex `image_gen` draws pictures from a prompt (2-4 minutes).

## Capabilities and Constraints

- The pet plays 96 x 100 frames on black; transparency becomes black; 128 colours per GIF.
- The artboard is 384 x 400 (4x); the server scales down.
- An empty state is made from idle frame 1 by puppet moves (tools/make-pack.sh); a drawn state
  plays its own frames.
- Agent control: design_* and canvas_* MCP tools; changes appear live in the page.

## Brand Commitments

- Name: Pet Studio (the designer is "Pet Studio Designer").
- Rule 6: AI-built work is labelled as AI-built.
- No binding visual identity exists yet. *(inferred: the v1 page is a utilitarian dark dashboard)*

## Evidence on Hand

- Real packs: lab/jc3248-pet-idf/data/characters (siamese, cat, neo, iris, …), and studio-made
  packs in workspace/packs (fox-scarf, mcp-design).
- No testimonials, users or metrics: do not invent any.

## Product Principles

1. The pet is the truth: preview what the device will actually show (96 x 100, on black).
2. Person and agent are equals: anything clickable is callable, and every change is visible.
3. Minutes, not tools: no build steps, file juggling or flashing knowledge on the designer's path.
4. Hand-made wins: a drawn frame always beats the generated one.
