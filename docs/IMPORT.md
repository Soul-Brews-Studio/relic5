# IMPORT: feeding the hub by hand

Nat, 2026-10-26: "remove all auto run", then "we will manual and make this cool later", then "we just do manual".
On m5 nothing feeds the relic5 hub by itself any more. An import runs when someone runs it.

## Run one

```sh
RELIC5_MACHINE=m5 bin/relic5-import        # from the relic5 checkout
~/relic5-reboot-test/m5-import.sh          # the same, on m5 (sets RELIC5_MACHINE=m5)
```

`bin/relic5-import` is a Bun script (`#!/usr/bin/env bun`, written with `Bun.$`); bun 1.3+ must be on the machine.
`RELIC5_MACHINE` is required: it is the name the hub files the rows under. A wrong name puts the rows under
another machine (that happened once, see `m5-nat` in docs/RETIRED.md). `RELIC5_HUB_URL` defaults to white
(`http://white.follow-rankine.ts.net:8795`).

## What it does

The same five steps as `~/.local/bin/relic-chain`, once:

| step | command | what it does |
|---|---|---|
| scan | `relic-scan run` | finds every agent home, parses new and grown transcripts, writes `~/.relic-scan/meta` and the map. Draws its own RELIC·SCAN box on the terminal; the import reads the run's summary from the last `job: "index"` line of `~/.relic-scan/_scans.jsonl` |
| extract | `relic-extract run` | cuts the new rows into chunks; its after hook pushes to white and runs `relic5 index --wait` there |
| push | `bin/relic5-push` | pushes again so the hub's per-machine versions refresh even when nothing was cut (a few seconds) |
| embed | `relic5 embed --limit 20000` | vectors for chunks that have none, on the ANE. AC power only; skipped on battery |
| sync | `relic-extract status --json` against `/api/status` | waits (up to 3 minutes) until the hub holds the same text, thinking and tools chunks as this machine. Both sides are read again on every try, since another scan may run beside this one. A stream that reports `error` never matches |

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
3. `~/relic5-reboot-test/m5-import.sh` when the hub should catch up.

The autostarts that used to do this, and everything else that started by itself on m5, are recorded in
docs/RETIRED.md (2026-10-26).

## Who owns what

The import only calls the other two tools; changes to them go to their repos (relic4-scan `docs/TALK.md`):

- `relic-scan run` and `_scans.jsonl`: relic4-scan.
- `relic-extract run` and `status --json` (relic-extract#45): relic-extract.
- `bin/relic5-import`, `bin/relic5-push` and the hub's `/api/status`: relic5.
