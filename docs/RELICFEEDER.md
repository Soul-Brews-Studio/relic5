# RelicFeeder: the menu-bar feeder for a Mac (plan, 2026-10-23)

> 2026-10-26: on m5 nothing feeds the hub by itself now (Nat: "we just do manual"). The relic-chain LaunchAgent is
> retired (docs/RETIRED.md) and imports run by hand with `bin/relic5-import` (docs/IMPORT.md). RelicFeeder stays a
> plan; a LaunchAgent for it needs Nat's OK.

Nat: "make swift daemon app to feed the relic5 white server, but search and learn first, we done a lot".
relic4-scan: "keep it to a menu-bar LaunchAgent that runs the same relic-chain steps and shows the hub's freshness card."

## What it is

A small SwiftUI `MenuBarExtra` app, run by a LaunchAgent. It runs the chain each machine already runs
(`relic-scan run`, then `relic-extract run`, whose after hook pushes to white and indexes), and it shows what the hub
says about this machine. It replaces nothing on day one: the existing `studio.soulbrews.relic-chain` job keeps running
until the app has worked for a day, then that job is unloaded (asked first).

## Reused, not rewritten (from the survey)

| piece | from | used for |
|---|---|---|
| `CLIProcess.swift` | agent-relic-v3 app/Sources/RelicMonitorRuntime | run relic-scan / relic-extract / relic5-push with an argument array, capture output, exit code |
| `JSONLJobTail.swift`, `MonitorModel` | agent-relic-v3 app/Sources/RelicMonitorCore | tail logs/jobs.jsonl-shaped events (the hub's /api/log gives the same shape) |
| `make_app.sh`, `remote/launchagent.zsh` | ane-oracle/tools/ane-embed-app | build a real .app bundle, write the LaunchAgent plist |
| theme / status rows | ANEEmbedBar | the look of the menu-bar panel |
| the ANE engine | ANEEmbedBar on 127.0.0.1:11435 | not linked: the embed step calls `relic5 embed` (policy: ANE for increments), which talks to it over HTTP |

## What the panel shows (all from the hub, no local guesses)

- This machine's row of `relic_status` freshness: newest row, behind now, last push, and the last SYNC line (OK / MISMATCH).
- The hub's warnings (none / disk / version / sync).
- The last 5 jobs of this machine from `/api/log` (push, index, embed), with rc.
- Vectors pending for this machine.
- Activity: the pass in flight, from `relic-scan ops --json --no-hub` (relic4-scan `src/ops.rs`, the same snapshot as
  its page's /ops and `relic-scan tui` tab 6), polled every 3 s while a pass runs and every 15 s when idle. Shows the
  stages marked ✓ done, ● running, · waiting, each with its time and typical time; a bar of elapsed over
  `typical_total_s`; "about M:SS left". When idle: how long the last pass took and when the next one starts.
- The menu-bar icon turns while a pass runs and shows the time left next to it. When the pass ends it shows ✓ (SYNC OK)
  or ✗ (MISMATCH) for 8 seconds, and the panel shows the SYNC line for those 8 seconds too.
- Buttons: "Run now" (one chain pass), "Open hub UI" (http://white.follow-rankine.ts.net:8795/), "Open log".

## The loop

Every 10 minutes (and on "Run now"): scan, then extract (its after hook pushes and indexes), then, on AC power only,
`relic5 embed` (policy picks ANE for an increment, says so in jobs.jsonl), then fetch status. One pass at a time: the
app holds a lock file, and each tool keeps its own lock. A failing step backs off (10, 20, 40 min, max 2 h) and the
panel shows the error line.

## Not in v1

- SMAppService login item (needs a signed bundle; past sessions deferred it: a1952607 06-08, 53102ba5 09-14). v1 uses a
  LaunchAgent plist, like the chain job.
- Any write to the hub except through the existing push (ssh) and embed shards.
- Linux: white keeps its systemd timer.

## Risks (from the survey)

1. Two writers: the app and the old chain job both run. Mitigation: the lock file, then unload the old job after a day.
2. CPU: ANEEmbedBar idles at 12–22%; the app must not add a busy loop (timer + Background QoS, no polling under 30 s).
3. macOS privacy prompts (mba hung 8 min on Desktop/Documents): the app never scans those folders (relic-scan's
   _config.json excludes them, as on mba), and a pass that sees no progress for 5 minutes is stopped and reported.

## Size

About 600 lines of Swift in one SwiftPM package (`feeder/`), plus `make_app.sh` and the plist; tests for the state
machine (lock, backoff, AC check) with fake processes.
