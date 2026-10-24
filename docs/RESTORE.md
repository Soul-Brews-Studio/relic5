# Backup and restore

The hub's data lives on one machine, white (`~/relic5`). m5 pulls a snapshot of it every night.

## What a snapshot holds

| kept | why |
|---|---|
| `parts/` | every machine's pushed history; the source of everything else |
| `vectors/` | about 1.1M embeddings; hours of ANE or gb300 time to redo |
| `resolve/` | the relic3 link table (old `relic3://` links) |
| `logs/` | jobs, queries, eval runs |
| `attic/` | retired data kept on purpose |
| `config/tokens` | the hub's token file; a hub restored without it locks every client out |
| `hub-status.json` | what the hub counted at backup time; the restore test compares against it |

Not kept: `index/` (the month manifests and BM25 tables, rebuilt from `parts/` by `relic5 index`) and `app/` (git).

Snapshots are `~/relic5-backup/white/<UTC yyyymmdd-hhmmss>/` on m5, `latest` points at the newest. Each one
hardlinks the files that did not change since the previous one, so a night costs only what changed. The newest 14
are kept (`RELIC5_BACKUP_KEEP`). The directories are 700.

## Schedule and the hub's view

- `deploy/launchd/studio.soulbrews.relic5-backup.plist`: 03:30 every night, backup then restore test.
  Install on m5: `cp deploy/launchd/studio.soulbrews.relic5-backup.plist ~/Library/LaunchAgents/ && launchctl load -w ~/Library/LaunchAgents/studio.soulbrews.relic5-backup.plist`
- Log: `~/Library/Logs/relic5-backup.log`.
- Each run writes a `backup` job (start, done or error) into white's `logs/jobs.jsonl`. `relic_status` shows it as
  `backup: {at, bytes, message, age_s}` and warns when there is none, or the newest is older than 36 h. The web UI
  shows it in the status strip and the Hub panel.

## Restore test

```sh
bin/relic5-restore-test                 # newest snapshot
bin/relic5-restore-test <snapshot>      # a given one
RELIC5_RESTORE_KEEP=1 bin/relic5-restore-test   # keep the scratch hub to look at
```

It clones `parts/` and `resolve/` into a scratch directory (APFS clone: no extra space), runs `relic5 index` there,
and compares the folded rows, every machine's rows per stream and the month count with `hub-status.json`. Exit 0
and `restore test PASSED` = the snapshot rebuilds the hub exactly. The snapshot itself is never written.

## Restoring white for real

1. Stop the hub: on white, `cd ~/relic5/app && docker compose down`.
2. Keep what is there: `mv ~/relic5 ~/relic5.broken-<date>` (nothing is deleted).
3. From m5, copy the snapshot back:
   `rsync -a ~/relic5-backup/white/latest/{parts,vectors,resolve,logs,attic} nat@white.follow-rankine.ts.net:relic5/`
   and the token file: `rsync -a ~/relic5-backup/white/latest/config/ nat@white.follow-rankine.ts.net:.config/relic5/`
4. Code: `git clone git@github.com:Soul-Brews-Studio/relic5 ~/relic5/app` (or move `app/` back from the broken copy).
5. Rebuild the index: `cd ~/relic5/app && just index` (then `relic5 index --vectors` for the vector tables).
6. Start it: `just up`; check `relic_status` (rows equal `hub-status.json`, no warnings).
7. Pushes since the snapshot come back by themselves: every machine's next relic-chain pass re-sends what the hub
   lacks (rsync compares sizes and mtimes).
