# relic3 certification (2026-10-24)

relic4-scan asked, for Nat: may relic3's data on m5 be deleted? Targets: `~/.relic3` (19 GB), `~/.relic3-hub` (80 GB) and
the `~/.relic3-mirror` sparsebundle (34 GB). This page is the evidence. The scripts and their outputs are in
`black:~/relic3-backup-20261024/` (and `/tmp/relic3cert` on m5 while it lasts).

The two relic3 indexes were read from their current generation (`index/_manifest/current`):

| index | run | prose rows | tool rows | uids | sessions |
|---|---|---|---|---|---|
| `~/.relic3` | 20261015-134354 | 2,071,675 | 4,116,979 | 6,188,654 | 151,398 |
| `~/.relic3-hub` | 20261024-091913 | 2,530,187 | 5,192,795 | 7,722,982 | 143,453 |

## 1. Sessions and messages are held in relic5

**Sessions.** relic3 counts each ψ note and memory note as a session (its sid is the note's path or name). Of the
relic3-hub sessions, 133,049 + 10,275 are notes and 630 are memory notes. All **9,774 transcript sessions** (9,495 in
`~/.relic3`) are held by relic5 (the hub has 122,777 sessions from m5, mba, white and jsonl-truth-import).

**Prose** (relic3-hub, 2,530,187 rows):

| how the row is held | rows |
|---|---|
| same message (msgkey) | 1,781,714 |
| same session and time | 65,682 |
| a relic5 row of the same session within 10 minutes | 357,178 |
| ψ notes / memory notes (checked below) | 152,205 |
| no relic5 row within 10 minutes | 173,408 |

The 173,408 rows fall in 371 sessions:

- 168,718 are three runaway Stop-hook loops of April 2026 (40940f85, 6958d7b9, 8930b58d). In 40940f85, 21,486 user
  rows are "Stop hook feedback: …" (4 distinct texts) and 21,491 assistant rows are a single invisible character
  (27 distinct texts). Each loop is counted twice, once in `peer-projects` and once in `projects-archive`.
  relic-extract cleans these rows out on purpose.
- The other 4,690 are `⏳` spinners, "No response requested.", API errors, "Conversation compacted", interrupt
  lines, slash commands, task notifications, 83 compaction summaries and a few hundred system recaps.
- The raw `.jsonl` of every one of the 371 sessions is still on m5, white or mba, except 4 Codex sessions (below).

**Tools** (relic3-hub): 2,348,158 of 2,425,166 tool calls (96.8%) match a relic5 tool row by session and time. relic5
keeps a tool's result in its call's row, so relic3's 2,767,629 separate result rows match only through their call.

**The 4 Codex sessions held nowhere else** (no raw file on any machine): 01a0525c, 01a093df, 01a0ad99, 01a0d5fd. Their
4,676 unmatched rows (177 prose and 4,499 tool rows) were imported as the machine `relic3-codex-import` (`~/.relic-import/relic3-codex`, through
relic-extract, pushed 2026-10-24 19:59). The hub's index grew by exactly those: tools_history +1,547 messages, prose_history +83.

**Notes.** 43,916 relic3 note paths are not placed in relic5's vault:

- 22,475 are still on disk.
- 21,303 were in removed neo-oracle worktrees, and the same file is in neo-oracle's main `ψ/`; 3 more are in its git history.
- 629 are memory notes, and every name is in relic5's memory layer.
- 136 exist nowhere but relic3: 91 notes (pulse team memory, book drafts, inbox, labs) and 45 `.venv` license files.
  They were exported back to files: white `~/relic5/attic/relic3-orphan-notes-20261024/` and
  black `~/relic3-backup-20261024/orphan-notes/`.

**The mirror.** All 32,894 sessions in `~/.relic3-mirror` (copies of white's and mba's homes) exist on white, mba or m5.

## 2. relic3 links resolve in relic5

`resolve/relic3.parquet` was rebuilt from both indexes: 7,742,386 uids (the 2026-10-23 copy, 7,720,974 uids, is
`resolve/relic3.parquet.bak-20261023`). Following relic_show's own steps:

| how a relic3 uid lands | uids |
|---|---|
| same message (msgkey) | 1,783,132 |
| ψ note by path | 112,872 |
| same session and time | 2,424,103 |
| nearest message of its session within 10 minutes | 3,197,303 |
| not placed | 224,976 |

So 97.1% land on a relic5 message. The 224,976 not placed are the rows above: the Stop-hook loops (about 173k user and
assistant rows), 48,694 notes whose path moved, 641 memory notes (relic_show does not map memory names yet), 1,459
tool rows and 1,171 system or developer rows. Live checks: 4 of 4 sampled `relic3://` links open in relic5.

## 3. Backup on black

`black:~/relic3-backup-20261024/` (700), written 2026-10-24 19:23–19:27, sha256-verified on black:

- `relic3/`: 2,137 files, 6.5 GB. `relic3-hub/`: 4,978 files, 10 GB. `<name>.sha256` and `<name>.files` beside each.
- Kept: `config/`, `logs/`, `cache/`, `index/_manifest/`, `index/_quarantine/`, `vectors/` and the current generation's
  parquet (2.1 GB and 2.5 GB: the whole corpus as each index last saw it).
- Not kept: older generations and `index/_search/` (BM25), both rebuilt from the parquet.
- `orphan-notes/`: the 136 notes above.
- `_scp-mistake-dir/`: a copy of two of my own lists, left by a wrong scp; it holds nothing of relic3.

## 4. Records

- The trinity rule and the ledger: [docs/RETIRED.md](RETIRED.md) (the row "relic3's data on m5").
- agent-relic-v3 `RETIRED.md`: relic3 is frozen and what replaced it.
