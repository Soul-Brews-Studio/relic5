# RETIRED: what relic5 stopped using, and what took its place

## The rule: trinity (เกิดขึ้น · ตั้งอยู่ · ดับไป)

Everything here goes through three stages: it arises, it persists, it ceases. "Nothing is deleted" covers only the
second stage. Nat, 2026-10-04 (herdr-oracle): "we shuld have trinity / เกิดขึ้น ตั้งอยู่ ดับไป that we should go not
only nothing deleted". Kept on its own, "nothing is deleted" is the anti-pattern *preservation without succession*: old indexes, servers and binaries that are still there and still look current, with nothing saying what
replaced them. relic3 answered from an index 9 days stale because of exactly this.

So retiring something takes three steps, and all three are written down:

1. **Cease as active.** Stop it from being used: unload the job, remove the MCP entry, move the folder out of `parts/`.
2. **Keep as record.** Move it, don't delete it. Write where it is kept and how to bring it back.
3. **Name what succeeded it.** Write what does its job now. If nothing does, write "nothing", together with the reason.

A retirement that is missing any of the three is not finished. Add one row below for each retirement, in the same
change that retires the thing.

On the hub, `relic5 seals --retire <machine> --why W --succeeded-by S` records step 3 for a machine's seals, next to
its seal records in `index/_seals/retired.json`, and logs a `retire` event in `logs/jobs.jsonl`.

## Ledger

| ceased | what | kept as record (restore) | succeeded by | why |
|---|---|---|---|---|
| 2026-10-23 | relic3 weeks imported into parts (`relic3-import`) | white `~/relic5/attic/relic3-import-20261023` | the `jsonl-truth-import` machine, plus relic3 links through `resolve/relic3.parquet` | one import path; old `relic3://` links still resolve |
| 2026-10-24 09:25 | relic3 `studio.soulbrews.relic-push` + `relic-indexer` LaunchAgents (m5) | `/tmp/studio.soulbrews.relic-{push,indexer}.plist.bak`; reload with `launchctl load -w` | relic-chain → relic5-push → the hub (later RelicFeeder) | two pipelines fed white for one job (Nat's decision) |
| 2026-10-24 | `m5-nat` parts pushed from the beta account by mistake | white `~/relic5/attic/m5-nat-beta-20261024` | m5 (beta's own scan) | it was beta's data under the wrong name |
| 2026-10-24 | MCP servers `relic3`, `session-viewer`, `session-search`, `session-dream`, `jsonl-indexer` (m5 `~/.claude.json`) | `~/.config/relic5/legacy-mcp-servers-20261024.json`; their indexes are untouched (`~/.relic3`, `~/.relic3-gens`, `sessions.db`, the labs) | relic5 MCP (`relic_*`), measured head to head in docs/APPS.md (d) | stale (9 to 41 days), about 6 GB resident |
| 2026-10-24 | skill `/relic3` and the relic3 or session-viewer calls in `ralph-dig`, `day-diary`, `oracle-recap-day`, `jsonl-truth`, `sonnet-scout`, `herdr-lead-scouts` | `SKILL.md.bak-20261024-relic5` beside each | skill `/relic5`; `/relic3` is now a redirect to it | the same tools, now on a live index |
| 2026-10-24 | `m5-nat` machine (nat's own relic chain, plist renamed `.off`) | white `~/relic5/attic/m5-nat-20261024`; 13 seal records in `index/_seals/retired.json` | m5: beta scans `/Users/Shared/nat-export` (transcripts), and `RELIC5_MEMORY_ROOTS` pushes nat's memory notes | one truth for m5. Every row and note was checked as held by m5 before the move (0 rows missing) |
| 2026-10-24 | replaced binaries and scripts: relic-scan (947 → 1312), relic5-push (stamps 4eed2b7, 039a4ee, 9a1c9e6), relic-chain (two edits) | `~/.local/bin/<name>.bak-<old version>` on m5, mba and white | the version `relic_status` reports per machine | each install keeps the binary it replaced |
| 2026-10-24 | relic3's data on m5: `~/.relic3` (19 GB), `~/.relic3-hub` (80 GB), `~/.relic3-mirror` (34 GB sparsebundle) | black `/home/beta/relic3-backup-20261024/` (user beta): both homes' config, logs, manifests, vectors and current-generation parquet (sha256 lists beside them), plus `orphan-notes/`; the 136 ψ notes that existed only in relic3 also in white `~/relic5/attic/relic3-orphan-notes-20261024` | relic5 hub: every relic3 transcript session held; `resolve/relic3.parquet` maps all 7,742,386 relic3 uids; the 4 Codex sessions held nowhere else imported as machine `relic3-codex-import` | relic3 frozen since 2026-10-15; certified in docs/RELIC3-CERTIFY.md |
| 2026-10-24 | `/Users/Shared/nat-export` (34 GB on m5): nat's one-time 14:07 copy of `.claude` and `.codex`, a relic-scan root and the `RELIC5_MEMORY_ROOTS` source | deleted 20:5x, after a check that every one of its 55,752 `.claude` and 4,124 `.codex` files is held at the same or bigger size elsewhere. First copied in, add-only: 11,531 files that were nowhere else to beta `~/.claude/backups/from-nat-export/`, and 4,121 Codex sessions to beta `~/.codex/sessions/` | beta's `~/.claude` and `~/.codex` are m5's one home. claude-sync (#49) keeps nat's `projects/` and `backups/` in it, and relic-scan reads it | one source of truth on m5 (Nat, 2026-10-24: "main should beta ~/.claude") |
| 2026-10-24 | `/opt/Code/_archive/oracle-world/nat-2026-06-10/.codex` (6.0 GB, nat's June Codex home: 1,001 rollouts, its log DB, package cache) and `~/.retired-2026-10-05` (1.3 GB: DustBoy worktrees and two repos, all pushed per its MANIFEST.md; only `.envrc` token files were local) on m5 | every session copied first, add-only, to beta `~/.codex/from-<folder>/` or `~/.claude/backups/from-<folder>/`; checked: 0 sessions not held at the same or bigger size; the repos are on GitHub | beta's `~/.claude` and `~/.codex` | one home on m5. The two rescue folders (`~/dup-rescue-alpha-2026-10-06`, `~/mba-rescue-2026-10-06`) had their sessions merged the same way but are kept: they hold 27 GB of rescued repo files |

## Not retired yet (each one needs Nat's OK, see docs/APPS.md)

- `studio.soulbrews.relic-chain` (m5). Its successor is RelicFeeder as a LaunchAgent. The plan is to wait a day
  after RelicFeeder runs on its own.
- The buildx cache (48 GB): a record with a successor (relic5); it is still undecided where it is kept.
- The old MCP entries in mba's and white's own `~/.claude.json`.
