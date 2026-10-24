# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Nat, the one owner of the fleet, checking once a day (morning, a few seconds) from m5 or a phone over tailscale:
is every machine's session history collected, synced and safe? Oracle agents read the same facts through MCP
(`relic_status`) and may link to the page when they report.

## Product Purpose

relic5 is one hub on white for every machine's Claude Code / Codex history: machines push month parts, the hub
folds them, indexes them for keyword search (BM25, Thai-aware) and holds vectors for semantic search, and serves it
all as MCP tools, an HTTP API and a web UI. Success: nothing said in any session is lost or unfindable, and when
something drifts (a machine stops pushing, a sync mismatches, the index or backup goes stale) it is seen the same day.

## Positioning

The only place where every machine's history meets: folded once per message across machines, partitioned by Bangkok
month (sealed months never change, the open month streams), with each machine's own SYNC verdict carried to the hub.

## Operating Context

- Feed: on each Mac/Linux box `relic-scan` → `relic-extract` → `bin/relic5-push` every 10 min (relic-chain
  LaunchAgent; RelicFeeder menu-bar app watches). The hub re-indexes after each push.
- Nightly: m5 pulls a backup snapshot and runs a restore test (docs/RESTORE.md).
- Reached only over tailscale (follow-rankine) or loopback; no public exposure.

## Capabilities and Constraints

- Data for the page: `GET /api/status` (machines, months, watermarks, freshness, store, resources, jobs, backup,
  warnings), `/api/log`, `/api/sessions`, `/api/queries`.
- Web UI: React + TypeScript + Tailwind v4 in `web/`, built into the Python package; no external requests (fonts,
  CDNs) and no Node on white.
- An unknown value is shown as unknown, never 0; every count says where it came from; failures are shown, never
  hidden (kept from relic3's app, agent-relic-v3 app/PRODUCT.md).

## Brand Commitments

The hub's visual system stays: jsonl-oracle Structor's Dark/Paper tokens (`web/src/index.css`), chosen by Nat
2026-10-24. New pages get new layouts inside it, not a new identity.

## Evidence on Hand

Live data from white's hub (4 machines: m5, white, mba, jsonl-truth-import; ~1.1M messages; 15 months). Reference
screens: agent-relic-v3 `scanner/docs/*.png` (Relic Scanner: Smart Scan, Embedding, Health, Banks & Repos, Jobs).

## Product Principles

1. A problem is never quieter than the good news around it.
2. Plain words and big numbers first; detail one click away.
3. Truth over polish: unknown stays unknown, every number traceable to its route.
4. One look answers "is everything in, current and safe?"

## Accessibility & Inclusion

Read on a phone as well as a desktop; Thai text in session content must render (Noto Sans Thai in the stack).
