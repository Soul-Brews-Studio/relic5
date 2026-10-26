# IMPORT: feeding the hub by hand

Nat, 2026-10-26: "remove all auto run", then "we just do manual", then "go fully manual, no auto import".
No machine feeds the relic5 hub by itself any more: m5's LaunchAgent is retired, white's `relic-chain.timer` is
disabled and mba's `studio.soulbrews.relic-chain` is booted out (relic4-scan, `docs/MANUAL.md` there). An import runs
when someone runs it, so the hub does not warn about an old push: `push_age_s` just says how old it is.

## Run one

```sh
relic5 import                      # the Rust CLI (docs/CLI.md); `relic5-import` still works and calls it
```

Once per machine: `echo m5 > ~/.config/relic5/machine` (the same file `relic5-push` reads), and `just cli` (docs/CLI.md). `RELIC5_MACHINE=…` still overrides the file.

`relic5 import` is part of the Rust CLI (`cli/src/import.rs`). Until 2026-10-26 it was `bin/relic5-import`, a Bun
script; that name is now a two-line shim to `relic5 import`.
The machine name is required (no hostname fallback): it is the name the hub files the rows under. A wrong name puts the rows under
another machine (that happened once, see `m5-nat` in docs/RETIRED.md). `RELIC5_HUB_URL` defaults to white
(`http://white.follow-rankine.ts.net:8795`).

## What it does

relic-chain's steps, once, with one push:

| step | command | what it does |
|---|---|---|
| scan | `relic-scan run` | finds every agent home, parses new and grown transcripts, writes `~/.relic-scan/meta` and the map. Draws its own RELIC·SCAN box on the terminal; the import reads the run's summary from the last `job: "index"` line of `~/.relic-scan/_scans.jsonl` |
| extract | `relic-extract run` | cuts the new rows into chunks. Its `after` hook is not used: on m5 it is commented out in `~/.arra/relic.toml` (old line kept there, backup `relic.toml.bak-20261026-after`) |
| push | `bin/relic5-push` | sends this machine's parts to white (only changed months move) |
| index | `ssh nat@white relic5 index --wait` | the hub takes the push into its index, so the sync below sees it at once |
| embed | `relic5 embed --limit 20000` | vectors for chunks that have none, on the ANE. AC power only; skipped on battery |
| sync | `relic-extract status --json` against `/api/status` | waits (up to 3 minutes) until, for each of text, thinking and tools, the hub holds at least what this run pushed and at most what this machine holds now (another pass may cut more beside this one). A stream that reports `error` never matches |

Every stage shows a spinner and its time, then `✓` or `✗ rc=N` with its last line. The run ends with one
RELIC5·IMPORT box: the hub's counts for this machine, the scan and cut figures, when it pushed, the newest row and
how far behind it is, and SYNC OK or MISMATCH. The border is amber when a stage failed or the counts disagree.
Every stage's output is appended to `~/Library/Logs/relic-chain.log` (or `RELIC_CHAIN_LOG`) in relic-chain's line format
(`chain start (m5)`, `run: scan …`, `run: done in Ns`, `… part(s) cut …`, `chain end`, `SYNC OK …`), so
`relic-scan ops` shows a manual import as a pass.

Exit code: 0 when every stage ran and the sync agreed; 1 when a stage failed; otherwise the sync result.

## Is the hub current?

```sh
curl -s http://white.follow-rankine.ts.net:8795/api/status \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['freshness']['machines']['m5'])"
```

`pushed_at` is the last import; `newest_ts` is the newest row the hub holds; `lag_s` is the gap between them.
The MCP tool `relic_status` shows the same per machine.

## After an m5 reboot

1. Log in, open herdr.
2. `~/relic5-reboot-test/m5-start.sh`: brings back the herdr sessions (neo, laris-co, arkkra, phd). It does not
   import.
3. `relic5 import` when the hub should catch up.

The autostarts that used to do this, and everything else that started by itself on m5, are recorded in
docs/RETIRED.md (2026-10-26).

## Who owns what

The import only calls the other two tools; changes to them go to their repos (relic4-scan `docs/TALK.md`):

- `relic-scan run` and `_scans.jsonl`: relic4-scan.
- `relic-extract run` and `status --json` (relic-extract#45): relic-extract.
- `relic5 import` (`cli/`), `bin/relic5-push` and the hub's `/api/status`: relic5.
